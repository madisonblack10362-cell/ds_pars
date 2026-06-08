"""
Модуль мониторинга Reddit для DayZ News Monitor.
Парсит сабреддиты через Playwright (headless Chromium) —
реальный браузер, как в Zennoposter, поэтому обходит блокировки ISP.

Логика по аналогии с Zennoparser:
  - NavigateAndWait — переход + ожидание React-рендера
  - IsPageBlocked — детекция Cloudflare/captcha/блокировок
  - 3 метода парсинга: shreddit-post DOM → <script id="data"> JSON → regex
  - Error streak — остановка после N ошибок подряд
  - Random delays между запросами
  - Детальное логирование

Установка:
  pip install playwright
  playwright install chromium
"""

import asyncio
import json
import random
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from database import Database
from logger import logger

try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# Пул потоков для синхронных фоллбэков
_thread_pool = ThreadPoolExecutor(max_workers=2)


class RedditMonitor:
    """
    Монитор сабреддитов Reddit через headless Chromium.
    Парсит DOM страницы после React-рендера, извлекает посты,
    фильтрует по рейтингу, извлекает текст, изображения и ссылки.
    """

    # Ключевые слова для фильтрации нежелательных постов (нижний регистр)
    BLACKLIST_KEYWORDS = [
        "playstation", "ps4", "ps5", "psn", "play station", "ps5 pro",
        "плойка", "плойке", "плойку", "плойкой",
        "консоль", "консоли", "консольная версия", "console",
    ]

    # Паттерны мнений/предложений — отсекаем до AI-анализа
    OPINION_PATTERNS = [
        "wouldn't it be", "wouldnt it be", "would be cool",
        "i think", "i believe", "i feel like", "i wish", "i hope",
        "they should", "we need", "we deserve", "bohemia should",
        "anyone else", "does anyone", "is it just me",
        "dayz 2", "dayz two", "sequel",
        "hire more", "larger team", "bigger team",
        "am i the only", "who else thinks",
        "can we get", "please add", "we want",
        "what if they", "imagine if",
        "unpopular opinion", "hot take",
        "this game is dead", "game is dying",
        "devs don't care", "developers don't",
        "fix this", "broken game", "waste of money",
        "not worth it", "refunded", "refund",
        "is dayz worth", "is dayz fun", "is dayz dead",
        "should i buy", "should i play",
        "how do i", "where can i", "can someone",
        "looking for group", "lfg", "lfm",
        "server looking", "recruiting",
        # Team size / budget / dev complaints
        "dev team is still so small", "fund a", "aaa budget",
        "dev team", "why is the team", "small team",
        "team is too small", "why are the devs",
        "hire more developers", "hire more devs",
        "bigger development team", "larger dev team",
        "single title", "fund a one time",
        "team size", "team needs to grow",
    ]

    def __init__(
        self,
        db: Database,
        subreddit_configs: list[dict],
        min_message_length: int = 20,
        min_score: int = 50,
        request_timeout: int = 30,
        max_retries: int = 3,
        user_agent: str | None = None,
        max_posts_per_check: int = 5,
        proxy: str = "",
    ):
        self.db = db
        self.subreddit_configs = subreddit_configs
        self.min_message_length = min_message_length
        self.min_score = min_score
        self.timeout = request_timeout
        self.max_retries = max_retries
        self.max_posts_per_check = max_posts_per_check

        # Playwright browser (lazy init)
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._playwright = None
        self._browser_lock = asyncio.Lock()

        # Error streak (как в Zennoparser)
        self._error_streak = 0
        self._max_error_streak = 5

        # Кэш обработанных post_id
        self._seen_post_ids: dict[str, str] = {}

        # Задержки (мс) — аналогия с Zennoparser v1.9
        self._page_load_timeout = 30000     # ms
        self._react_render_delay = 4000     # ms — ждать React
        self._extra_render_delay = 3000     # ms — догрузка
        self._min_delay_between = 8          # сек между сабреддитами
        self._max_delay_between = 15         # сек между сабреддитами

        if not HAS_PLAYWRIGHT:
            logger.error(
                "RedditMonitor: playwright НЕ установлен! "
                "Установи: pip install playwright && playwright install chromium"
            )

    # =====================================================================
    # Browser lifecycle
    # =====================================================================

    async def _ensure_browser(self) -> BrowserContext | None:
        """Ленивая инициализация браузера. Потокобезопасно."""
        async with self._browser_lock:
            if self._context and self._context.pages:
                return self._context

            if not HAS_PLAYWRIGHT:
                logger.error("RedditMonitor: playwright не установлен")
                return None

            try:
                self._playwright = await async_playwright().start()

                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                ]

                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=launch_args,
                )

                self._context = await self._browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                )

                logger.info("RedditMonitor: Chromium запущен (headless)")
                return self._context

            except Exception as e:
                logger.error("RedditMonitor: не удалось запустить Chromium: %s", e)
                return None

    async def close_browser(self) -> None:
        """Закрывает браузер и освобождает ресурсы."""
        async with self._browser_lock:
            try:
                if self._context:
                    await self._context.close()
                    self._context = None
                if self._browser:
                    await self._browser.close()
                    self._browser = None
                if self._playwright:
                    await self._playwright.stop()
                    self._playwright = None
                logger.info("RedditMonitor: Chromium закрыт")
            except Exception as e:
                logger.warning("RedditMonitor: ошибка закрытия браузера: %s", e)

    # =====================================================================
    # Block detection (по аналогии с Zennoparser IsPageBlocked)
    # =====================================================================

    @staticmethod
    def _is_blocked_text(text: str) -> bool:
        """Проверяет текст страницы на маркеры блокировки (Cloudflare, captcha и т.д.)."""
        if not text:
            return True

        block_markers = [
            "blocked",
            "captcha",
            "CAPTCHA",
            "Captcha",
            "Too Many Requests",
            "Access denied",
            "Доступ ограничен",
            "Доступ заблокирован",
            "доступ временно ограничен",
            "Security Checkpoint",
            "Service Unavailable",
            "503",
            "Error 403",
            "Forbidden",
            "cloudflare",
            "Cloudflare",
            "just a moment",
            "checking your browser",
            "network security",
            "You've been blocked",
        ]

        for marker in block_markers:
            if marker in text:
                return True

        # Если страница слишком короткая и не содержит постов — скорее всего блок
        if len(text) < 500 and "post" not in text.lower():
            return True

        return False

    # =====================================================================
    # Navigate & Wait (по аналогии с Zennoparser NavigateAndWait)
    # =====================================================================

    async def _navigate_and_wait(
        self, page: Page, url: str, wait_selector: str = "shreddit-post"
    ) -> bool:
        """
        Переходит по URL, ждёт рендер React, проверяет блокировки.
        Возвращает True если страница загружена успешно.
        """
        try:
            logger.info("RedditMonitor: NavigateAndWait → %s", url)
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._page_load_timeout,
            )

            # Ждём React рендер (аналог reactRenderDelay в Zennoparser)
            await asyncio.sleep(self._react_render_delay / 1000)

            # Проверяем блокировку ДО ожидания элементов
            page_text = await page.text_content("body") or ""
            if self._is_blocked_text(page_text):
                logger.warning("RedditMonitor: БЛОКИРОВКА обнаружена на %s", url)
                return False

            # Ждём появления постов
            if wait_selector:
                try:
                    await page.wait_for_selector(
                        wait_selector,
                        timeout=self._extra_render_delay,
                    )
                except Exception:
                    # Возможно старый Reddit — пробуем другие селекторы
                    logger.debug("RedditMonitor: wait_for_selector(%s) timeout, пробуем фоллбэк", wait_selector)
                    # Дополнительная задержка на догрузку
                    await asyncio.sleep(self._extra_render_delay / 1000)

            # Повторная проверка после ожидания
            page_text = await page.text_content("body") or ""
            if self._is_blocked_text(page_text):
                logger.warning("RedditMonitor: БЛОКИРОВКА после ожидания на %s", url)
                return False

            return True

        except Exception as e:
            logger.error("RedditMonitor: NavigateAndWait ошибка: %s", e)
            return False

    # =====================================================================
    # Parsing methods (3 fallback — как в Zennoparser)
    # =====================================================================

    async def _parse_posts_method1_dom(self, page: Page) -> list[dict]:
        """
        Метод 1: Парсинг shreddit-post элементов (новый Reddit 2024).
        Каждый <shreddit-post> имеет data-атрибуты с информацией о посте.
        """
        posts = []

        try:
            elements = await page.query_selector_all("shreddit-post")
            logger.info("RedditMonitor: Метод1 (DOM) — найдено %d shreddit-post", len(elements))

            for el in elements:
                try:
                    # shreddit-post render props (через get_attribute на element)
                    title = await el.get_attribute("post-title") or ""
                    post_url = await el.get_attribute("content-href") or ""
                    score_str = await el.get_attribute("score") or "0"
                    comment_count_str = await el.get_attribute("comment-count") or "0"
                    author = await el.get_attribute("author") or ""
                    post_id = await el.get_attribute("id") or ""
                    post_type = await el.get_attribute("post-type") or "link"

                    if not title:
                        # Пробуем получить текст из вложенного h3/a
                        title_el = await el.query_selector("a[slot='title'], h3")
                        if title_el:
                            title = (await title_el.text_content() or "").strip()

                    if not title:
                        continue

                    # Извлекаем ID из URL: /r/dayz/comments/abc123/...
                    if post_url:
                        id_match = re.search(r"/comments/([a-z0-9]+)/", post_url)
                        if id_match:
                            post_id = id_match.group(1)

                    # Парсим score
                    score = 0
                    if isinstance(score_str, str):
                        # Reddit показывает "1.2k" и т.д.
                        score_str = score_str.replace(",", "").strip()
                        if score_str.endswith("k"):
                            try:
                                score = int(float(score_str[:-1]) * 1000)
                            except ValueError:
                                score = 0
                        else:
                            try:
                                score = int(score_str)
                            except ValueError:
                                score = 0

                    # Парсим comment count
                    comment_count = 0
                    if isinstance(comment_count_str, str):
                        comment_count_str = comment_count_str.replace(",", "").strip()
                        if comment_count_str.endswith("k"):
                            try:
                                comment_count = int(float(comment_count_str[:-1]) * 1000)
                            except ValueError:
                                comment_count = 0
                        else:
                            try:
                                comment_count = int(comment_count_str)
                            except ValueError:
                                comment_count = 0

                    # Извлекаем preview image
                    images = []
                    img_el = await el.query_selector("img[alt='Post preview'], img[src*='preview']")
                    if img_el:
                        img_src = await img_el.get_attribute("src") or ""
                        if img_src and img_src.startswith("http"):
                            images.append(img_src)

                    # Извлекаем selftext если есть
                    selftext = ""
                    if post_type == "self":
                        text_el = await el.query_selector("div[slot='text-content'], p")
                        if text_el:
                            selftext = (await text_el.text_content() or "").strip()

                    # Извлекаем outbound link
                    outbound_link = ""
                    if post_type == "link":
                        link_el = await el.query_selector("a[href^='https://'][outbound], a[data-click-id='outbound']")
                        if link_el:
                            outbound_link = await link_el.get_attribute("href") or ""

                    posts.append({
                        "id": post_id,
                        "title": title.strip(),
                        "url": post_url,
                        "score": score,
                        "comment_count": comment_count,
                        "author": author,
                        "selftext": selftext,
                        "post_type": post_type,
                        "images": images,
                        "outbound_link": outbound_link,
                        "parse_method": "dom",
                    })

                except Exception as e:
                    logger.debug("RedditMonitor: ошибка парсинга shreddit-post: %s", e)
                    continue

        except Exception as e:
            logger.debug("RedditMonitor: Метод1 (DOM) ошибка: %s", e)

        return posts

    async def _parse_posts_method2_embedded_json(self, page: Page) -> list[dict]:
        """
        Метод 2: Парсинг встроенного JSON из <script id="data">.
        Reddit встраивает структурированные данные о постах в страницу.
        """
        posts = []

        try:
            script_el = await page.query_selector("script#data")
            if not script_el:
                logger.debug("RedditMonitor: Метод2 (JSON) — <script id='data'> не найден")
                return posts

            raw_json = await script_el.content() or ""

            # Reddit embeds the data as JSON inside the script
            # Ищем массив постов через regex
            # Формат: {"posts":{"t3_XXXX":{...}, ...}}
            post_blocks = re.findall(r'"t3_([a-z0-9]+)":\s*\{([^}]*(?:"title"[^}]*"score"[^}]*))\}', raw_json)
            if not post_blocks:
                # Альтернативный паттерн — ищем title рядом с id
                post_blocks = re.findall(
                    r'"id"\s*:\s*"t3_([a-z0-9]+)"[^}]*?'
                    r'"title"\s*:\s*"([^"]*(?:\\.[^"]*)*)"',
                    raw_json,
                )

            logger.info("RedditMonitor: Метод2 (JSON) — найдено %d блоков", len(post_blocks))

            for block in post_blocks:
                try:
                    if isinstance(block, tuple) and len(block) == 2:
                        post_id = block[0]
                        title = block[1].replace('\\"', '"').replace("\\'", "'")
                        posts.append({
                            "id": post_id,
                            "title": title,
                            "url": f"https://www.reddit.com/r/dayz/comments/{post_id}/",
                            "score": 0,
                            "comment_count": 0,
                            "author": "",
                            "selftext": "",
                            "post_type": "unknown",
                            "images": [],
                            "outbound_link": "",
                            "parse_method": "json_embedded",
                        })
                    elif isinstance(block, str):
                        # Более глубокий парсинг
                        title_match = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', block)
                        score_match = re.search(r'"score"\s*:\s*(\d+)', block)
                        if title_match:
                            posts.append({
                                "id": "",
                                "title": title_match.group(1).replace('\\"', '"'),
                                "score": int(score_match.group(1)) if score_match else 0,
                                "parse_method": "json_embedded",
                            })

                except Exception as e:
                    logger.debug("RedditMonitor: Метод2 ошибка парсинга блока: %s", e)
                    continue

        except Exception as e:
            logger.debug("RedditMonitor: Метод2 (JSON) ошибка: %s", e)

        return posts

    async def _parse_posts_method3_regex(self, page: Page) -> list[dict]:
        """
        Метод 3: Regex-парсинг HTML текста страницы (последний фоллбэк).
        Ищем паттерны постов в сыром HTML.
        """
        posts = []

        try:
            html_content = await page.content()

            # Ищем ссылки на посты /comments/XXXXX/
            post_urls = re.findall(
                r'href="(/r/\w+/comments/([a-z0-9]+)/[^"]*)"', html_content
            )
            logger.info(
                "RedditMonitor: Метод3 (Regex) — найдено %d ссылок /comments/",
                len(post_urls),
            )

            seen_ids = set()
            for url_path, post_id in post_urls:
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                # Ищем title рядом с URL
                title = ""
                # Reddit часто ставит title в data-testid или aria-label
                title_patterns = [
                    rf'{re.escape(url_path)}[^>]*title="([^"]+)"',
                    rf'title="([^"]+)"[^<]*{re.escape(post_id)}',
                    rf'{re.escape(post_id)}.*?<h[23][^>]*>([^<]+)<',
                    rf'data-testid="post-title"[^>]*>([^<]+)<',
                ]
                for pat in title_patterns:
                    match = re.search(pat, html_content, re.DOTALL)
                    if match:
                        title = match.group(1).strip()
                        break

                if not title:
                    # Последний шанс — ищем текст в href附近的 <a>
                    title = f"Reddit post {post_id}"

                full_url = f"https://www.reddit.com{url_path}"

                posts.append({
                    "id": post_id,
                    "title": title,
                    "url": full_url,
                    "score": 0,
                    "comment_count": 0,
                    "author": "",
                    "selftext": "",
                    "post_type": "unknown",
                    "images": [],
                    "outbound_link": "",
                    "parse_method": "regex",
                })

        except Exception as e:
            logger.debug("RedditMonitor: Метод3 (Regex) ошибка: %s", e)

        return posts

    async def _parse_posts_fallback_old_reddit(self, page: Page) -> list[dict]:
        """
        Метод 4 (bonus): Парсинг old.reddit.com HTML.
        Old Reddit рендерит простой HTML без React — легко парсить.
        """
        posts = []

        try:
            # Old Reddit использует <div id="siteTable"> с .thing элементами
            elements = await page.query_selector_all("#siteTable .thing.link")
            logger.info(
                "RedditMonitor: Метод4 (OldReddit) — найдено %d .thing.link",
                len(elements),
            )

            for el in elements:
                try:
                    # Title
                    title_el = await el.query_selector("a.title, p.title")
                    title = (await title_el.text_content() or "").strip() if title_el else ""
                    if not title:
                        continue

                    # URL
                    comments_url = await el.query_selector("a.comments, a.bylink")
                    comments_href = await comments_url.get_attribute("href") or "" if comments_url else ""

                    # Post ID из data-fullname (t3_XXXXX)
                    fullname = await el.get_attribute("data-fullname") or ""
                    post_id = fullname.replace("t3_", "") if fullname else ""

                    # Score
                    score_el = await el.query_selector(".score.unvoted, .score.likes")
                    score_text = (await score_el.text_content() or "0").strip() if score_el else "0"
                    score = int(score_text.replace(",", "")) if score_text.isdigit() else 0

                    # Author
                    author_el = await el.query_selector(".author")
                    author = (await author_el.text_content() or "").strip() if author_el else ""

                    # Domain (external link or self.)
                    domain_el = await el.query_selector(".domain > a, .domain")
                    domain = (await domain_el.text_content() or "").strip() if domain_el else ""
                    is_self = "self." in domain

                    # Thumbnail image
                    images = []
                    thumb_el = await el.query_selector("a.thumbnail img, .thumbnail img")
                    if thumb_el:
                        img_src = await thumb_el.get_attribute("src") or ""
                        if img_src and not img_src.startswith("data:") and "redditstatic" not in img_src:
                            images.append(img_src)

                    # Selftext preview
                    selftext = ""
                    if is_self:
                        exp_el = await el.query_selector(".expando .md, .usertext-body .md")
                        if exp_el:
                            selftext = (await exp_el.text_content() or "").strip()

                    # Outbound link
                    outbound_link = ""
                    if not is_self:
                        title_link_el = await el.query_selector("a.title")
                        if title_link_el:
                            href = await title_link_el.get_attribute("href") or ""
                            if href and not href.startswith("/r/"):
                                outbound_link = href

                    # num_comments
                    comments_text = ""
                    comments_link = await el.query_selector(".comments")
                    if comments_link:
                        comments_text = (await comments_link.text_content() or "").strip()
                    comment_count = 0
                    cm = re.search(r"(\d+)", comments_text)
                    if cm:
                        comment_count = int(cm.group(1))

                    posts.append({
                        "id": post_id,
                        "title": title,
                        "url": comments_href,
                        "score": score,
                        "comment_count": comment_count,
                        "author": author,
                        "selftext": selftext,
                        "post_type": "self" if is_self else "link",
                        "images": images,
                        "outbound_link": outbound_link,
                        "parse_method": "old_reddit",
                    })

                except Exception as e:
                    logger.debug("RedditMonitor: Метод4 ошибка парсинга .thing: %s", e)
                    continue

        except Exception as e:
            logger.debug("RedditMonitor: Метод4 (OldReddit) ошибка: %s", e)

        return posts

    # =====================================================================
    # Обработка поста (сохранение в БД) — почти без изменений
    # =====================================================================

    async def _process_parsed_post(
        self, post: dict, subreddit: str, min_score: int
    ) -> str:
        """
        Обрабатывает один распарсенный пост.
        Returns: 'saved' | 'seen' | 'score' | 'blacklist' | 'skip'
        """
        post_id = post.get("id", "")
        if not post_id:
            return "skip"

        external_id = f"reddit_{subreddit}_{post_id}"

        if external_id in self._seen_post_ids:
            return "seen"

        if await self.db.is_message_processed("reddit", subreddit, external_id):
            self._seen_post_ids[external_id] = external_id
            return "seen"

        score = post.get("score", 0)

        if score < min_score:
            logger.debug(
                "RedditMonitor: r/%s '%s' score=%d < %d",
                subreddit, post.get("title", "")[:40], score, min_score,
            )
            return "score"

        title = post.get("title", "").strip()
        if not title:
            return "skip"

        # Очистка HTML entities
        title = re.sub(r"<[^>]+>", "", title)
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')

        author = post.get("author", "")
        if author.startswith("u/"):
            author = author[2:]

        selftext = post.get("selftext", "")
        selftext = re.sub(r"<[^>]+>", "", selftext)
        selftext = selftext.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        selftext = selftext.strip()

        text = selftext if len(selftext) > len(title) else title

        # Blacklist
        check_text = f"{title} {text}".lower()
        for keyword in self.BLACKLIST_KEYWORDS:
            if keyword in check_text:
                self._seen_post_ids[external_id] = external_id
                logger.info(
                    "RedditMonitor: пропущен (blacklist '%s'): %s",
                    keyword, title[:60],
                )
                return "blacklist"

        # Opinion filter
        title_lower = title.lower()
        selftext_lower = selftext.lower()
        for pattern in self.OPINION_PATTERNS:
            if pattern in title_lower or (selftext and pattern in selftext_lower[:200]):
                self._seen_post_ids[external_id] = external_id
                logger.info(
                    "RedditMonitor: пропущен (мнение '%s'): %s (score=%d)",
                    pattern, title[:60], score,
                )
                return "blacklist"

        if len(text) < self.min_message_length:
            return "skip"

        # Images
        images = list(post.get("images", []))
        outbound_link = post.get("outbound_link", "")
        if outbound_link and outbound_link.startswith("https://i.redd.it/"):
            if outbound_link not in images:
                images.append(outbound_link)
        img_urls = re.findall(r"https?://i\.redd\.it/\S+", text)
        for img_url in img_urls:
            if img_url not in images:
                images.append(img_url)

        # Links
        links = []
        all_links = re.findall(r"https?://[^\s<>\"'\)]+", text)
        for tl in all_links:
            if "redd.it" not in tl and "reddit.com" not in tl and tl != outbound_link:
                links.append(tl)
        if outbound_link and outbound_link.startswith("http") and "reddit.com" not in outbound_link:
            links.append(outbound_link)

        # Server name
        server_name = f"r/{subreddit}"

        await self.db.register_source(
            source_type="reddit",
            server_name=server_name,
            source_id=subreddit,
            extra={"min_score": min_score},
        )

        msg_id = await self.db.save_message(
            external_id=external_id,
            source_type="reddit",
            source_id=subreddit,
            server_name=server_name,
            text=text,
            title=title,
            channel_name=subreddit,
            author=author or "unknown",
            images=images,
            links=links,
            published_at_source=None,
        )

        if msg_id:
            self._seen_post_ids[external_id] = external_id
            comment_count = post.get("comment_count", 0)
            parse_method = post.get("parse_method", "?")
            logger.info(
                "RedditMonitor: #%d сохранён (r/%s, score=%d, comments=%d, %d симв, %d фото, [%s])",
                msg_id, subreddit, score, comment_count,
                len(text), len(images), parse_method,
            )
            return "saved"

        return "skip"

    # =====================================================================
    # Основной парсинг сабреддита
    # =====================================================================

    async def _check_subreddit_browser(
        self, subreddit: str, sort_type: str, min_score: int, budget: int = 100
    ) -> int:
        """
        Парсит сабреддит через headless Chromium.
        Пробует www.reddit.com, затем old.reddit.com.
        """
        context = await self._ensure_browser()
        if not context:
            logger.error("RedditMonitor: браузер не доступен")
            return 0

        urls_to_try = [
            f"https://www.reddit.com/r/{subreddit}/{sort_type}/",
            f"https://old.reddit.com/r/{subreddit}/{sort_type}/",
        ]

        for url in urls_to_try:
            is_old = "old.reddit" in url

            for attempt in range(1, self.max_retries + 1):
                try:
                    page = await context.new_page()

                    try:
                        # NavigateAndWait (как в Zennoparser)
                        wait_sel = "shreddit-post" if not is_old else "#siteTable .thing"
                        success = await self._navigate_and_wait(page, url, wait_selector=wait_sel)

                        if not success:
                            self._error_streak += 1
                            if self._error_streak >= self._max_error_streak:
                                logger.error(
                                    "RedditMonitor: %d ошибок подряд — СТОП (error streak)",
                                    self._error_streak,
                                )
                                return 0

                            logger.warning(
                                "RedditMonitor: r/%s блокировка (попытка %d/%d, url=%s)",
                                subreddit, attempt, self.max_retries, url,
                            )
                            if attempt < self.max_retries:
                                delay = random.randint(10, 20)
                                logger.info("RedditMonitor: жду %d сек перед повтором...", delay)
                                await asyncio.sleep(delay)
                            continue

                        # Успешная загрузка — сбрасываем error streak
                        self._error_streak = 0

                        # Парсинг постов (3 метода fallback, как в Zennoparser)
                        posts = []

                        if not is_old:
                            # Метод 1: DOM (shreddit-post)
                            posts = await self._parse_posts_method1_dom(page)

                            # Метод 2: Embedded JSON (если метод 1 не дал результатов)
                            if not posts:
                                logger.info("RedditMonitor: DOM не дал постов — пробуем JSON")
                                posts = await self._parse_posts_method2_embedded_json(page)

                            # Метод 3: Regex (последний шанс для new Reddit)
                            if not posts:
                                logger.info("RedditMonitor: JSON не дал постов — пробуем regex")
                                posts = await self._parse_posts_method3_regex(page)
                        else:
                            # Old Reddit — прямой парсинг HTML
                            posts = await self._parse_posts_fallback_old_reddit(page)

                        if not posts:
                            logger.info("RedditMonitor: r/%s — 0 постов найдено (%s)", subreddit, url)
                            break  # Не пытаемся retry если постов просто нет

                        # Дедупликация по ID в пределах этой страницы
                        seen = set()
                        unique_posts = []
                        for p in posts:
                            pid = p.get("id", "")
                            if pid and pid not in seen:
                                seen.add(pid)
                                unique_posts.append(p)
                        posts = unique_posts

                        # Обработка постов
                        new_count = 0
                        skipped_score = 0
                        skipped_seen = 0
                        skipped_blacklist = 0

                        for post in posts:
                            if new_count >= budget:
                                break

                            result = await self._process_parsed_post(
                                post, subreddit, min_score
                            )

                            if result == "saved":
                                new_count += 1
                            elif result == "seen":
                                skipped_seen += 1
                            elif result == "score":
                                skipped_score += 1
                            elif result == "blacklist":
                                skipped_blacklist += 1

                        logger.info(
                            "RedditMonitor: r/%s — %d постов, %d новых, "
                            "%d по score, %d видели, %d blacklist [%s]",
                            subreddit, len(posts), new_count,
                            skipped_score, skipped_seen, skipped_blacklist,
                            url,
                        )
                        return new_count

                    finally:
                        await page.close()

                except Exception as exc:
                    self._error_streak += 1
                    logger.warning(
                        "RedditMonitor: ошибка r/%s (попытка %d/%d): %s",
                        subreddit, attempt, self.max_retries, exc,
                    )

                    if self._error_streak >= self._max_error_streak:
                        logger.error(
                            "RedditMonitor: %d ошибок подряд — СТОП",
                            self._error_streak,
                        )
                        return 0

                    if attempt < self.max_retries:
                        delay = random.randint(10, 20)
                        logger.info("RedditMonitor: жду %d сек перед повтором...", delay)
                        await asyncio.sleep(delay)

        return 0

    # =====================================================================
    # Public API (без изменений интерфейса)
    # =====================================================================

    async def load_initial_state(self) -> None:
        """Предзагружает кэш из базы данных."""
        messages = await self.db.get_recent_messages(hours=720, limit=1000)
        count = 0
        for msg in messages:
            if msg.get("source_type") == "reddit":
                self._seen_post_ids[msg["external_id"]] = msg["external_id"]
                count += 1
        logger.info("RedditMonitor: кэш загружен (%d постов)", count)

    async def check_all_subreddits(self) -> int:
        """Проверяет все настроенные сабреддиты через headless Chromium."""
        if not HAS_PLAYWRIGHT:
            logger.error(
                "RedditMonitor: playwright НЕ установлен! "
                "Установи: pip install playwright && playwright install chromium"
            )
            return 0

        total_new = 0

        for i, cfg in enumerate(self.subreddit_configs):
            subreddit = cfg.get("subreddit", "")
            if not subreddit:
                continue

            sort_type = cfg.get("sort", "hot")
            min_score = cfg.get("min_score", self.min_score)

            remaining = self.max_posts_per_check - total_new
            if remaining <= 0:
                logger.info(
                    "RedditMonitor: достигнут лимит %d постов за проверку",
                    self.max_posts_per_check,
                )
                break

            count = await self._check_subreddit_browser(
                subreddit, sort_type, min_score, budget=remaining
            )
            total_new += count

            # Random delay между сабреддитами (как в Zennoparser)
            if i < len(self.subreddit_configs) - 1:
                delay = random.randint(self._min_delay_between, self._max_delay_between)
                logger.info("RedditMonitor: жду %d сек перед следующим сабреддитом...", delay)
                await asyncio.sleep(delay)

        if total_new > 0:
            logger.info(
                "RedditMonitor: найдено %d новых постов на всех сабреддитах",
                total_new,
            )

        return total_new
