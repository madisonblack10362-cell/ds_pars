"""
Модуль мониторинга Reddit для DayZ News Monitor.
Парсит сабреддиты через Reddit JSON API (с score),
фильтрует по рейтингу, извлекает текст, изображения и ссылки.

Использует системный curl как основной метод (надёжнее всего),
curl_cffi и urllib как фоллбэки.
"""

import asyncio
import json
import re
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from ssl import create_default_context

from database import Database
from logger import logger

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


# Reddit JSON API — возвращает посты с реальным score
REDDIT_JSON_URL = "https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}&raw_json=1"

# Пул потоков
_thread_pool = ThreadPoolExecutor(max_workers=4)

# Лог первой ошибки каждого метода
_first_error_logged: set[str] = set()


def _do_request_system_curl(url: str, timeout: int, proxy: str = "") -> dict | str:
    """Запрос через системный curl (самый надёжный метод)."""
    try:
        cmd = [
            "curl", "-s", "-f",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "-H", "Accept: application/json, text/plain, */*",
            "-H", "Accept-Language: en-US,en;q=0.5",
            "--max-time", str(timeout),
            "--compressed",
        ]
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.append(url)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        if result.returncode == 22:
            return f"curl HTTP 403/404"
        stderr = result.stderr.strip()[:200] if result.stderr else f"exit code {result.returncode}"
        return f"curl ошибка: {stderr}"
    except FileNotFoundError:
        return "curl не найден"
    except subprocess.TimeoutExpired:
        return "curl таймаут"
    except json.JSONDecodeError as e:
        return f"curl JSON ошибка: {e}"
    except Exception as e:
        return f"curl ошибка: {type(e).__name__}: {e}"


def _do_request_curl_cffi(url: str, timeout: int, proxy: str = "") -> dict | str | None:
    """Запрос через curl_cffi."""
    try:
        kwargs = dict(
            url=url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.5",
            },
            timeout=timeout,
            impersonate="chrome",
        )
        if proxy:
            kwargs["proxies"] = {"https": proxy, "http": proxy}
        resp = curl_requests.get(**kwargs)
        if resp.status_code == 200:
            return resp.json()
        return f"curl_cffi HTTP {resp.status_code}"
    except Exception as e:
        return f"curl_cffi ошибка: {type(e).__name__}: {e}"


def _do_request_urllib(url: str, timeout: int, proxy: str = "") -> dict | str:
    """Запрос через urllib (фоллбэк)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        })
        if proxy:
            req.set_proxy(proxy, "https")
        ctx = create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if resp.status == 200:
                return json.loads(resp.read())
            return f"urllib HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return f"urllib HTTP {e.code}"
    except Exception as e:
        return f"urllib ошибка: {type(e).__name__}: {e}"


class RedditMonitor:
    """
    Монитор сабреддитов Reddit.
    Парсит JSON API, фильтрует по минимальному рейтингу,
    извлекает текст, self-post контент, изображения и ссылки.
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
        self.proxy = proxy

        # Методы в порядке приоритета
        self._methods: list[tuple[str, callable]] = [
            ("curl", _do_request_system_curl),
        ]
        if HAS_CURL_CFFI:
            self._methods.append(("curl_cffi", _do_request_curl_cffi))
        self._methods.append(("urllib", _do_request_urllib))

        methods_str = ", ".join(m[0] for m in self._methods)
        logger.info("RedditMonitor: методы запроса: %s", methods_str)

        # Кэш обработанных post_id
        self._seen_post_ids: dict[str, str] = {}

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
        """Проверяет все настроенные сабреддиты через JSON API."""
        total_new = 0

        for cfg in self.subreddit_configs:
            subreddit = cfg.get("subreddit", "")
            if not subreddit:
                continue

            sort_type = cfg.get("sort", "hot")
            limit = min(cfg.get("limit", 25), 100)
            min_score = cfg.get("min_score", self.min_score)

            remaining = self.max_posts_per_check - total_new
            if remaining <= 0:
                logger.info(
                    "RedditMonitor: достигнут лимит %d постов за проверку",
                    self.max_posts_per_check,
                )
                break
            count = await self._check_subreddit_json(
                subreddit, sort_type, limit, min_score, budget=remaining
            )
            total_new += count

        if total_new > 0:
            logger.info(
                "RedditMonitor: найдено %d новых постов на всех сабреддитах",
                total_new,
            )
        return total_new

    def _fetch_reddit(self, url: str) -> dict | None:
        """
        Пробует все методы по порядку.
        Возвращает dict с данными или None если все упали.
        """
        errors: list[str] = []

        for method_name, func in self._methods:
            result = func(url, self.timeout, proxy=self.proxy)

            if isinstance(result, dict):
                if errors:
                    logger.info("RedditMonitor: %s сработал (пред.: %s)", method_name, "; ".join(errors))
                return result

            if isinstance(result, str):
                errors.append(f"{method_name}: {result}")
                if method_name not in _first_error_logged:
                    _first_error_logged.add(method_name)
                    logger.warning("RedditMonitor: %s не работает — %s", method_name, result)

        logger.error("RedditMonitor: ВСЕ методы упали: %s", " | ".join(errors))
        return None

    async def _check_subreddit_json(
        self, subreddit: str, sort_type: str, limit: int, min_score: int, budget: int = 100
    ) -> int:
        """Парсит сабреддит через Reddit JSON API."""
        url = REDDIT_JSON_URL.format(subreddit=subreddit, sort=sort_type, limit=limit)

        for attempt in range(1, self.max_retries + 1):
            try:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(_thread_pool, self._fetch_reddit, url)

                if data is None:
                    logger.warning(
                        "RedditMonitor: r/%s — не удалось (попытка %d/%d)",
                        subreddit, attempt, self.max_retries,
                    )
                    if attempt < self.max_retries:
                        await asyncio.sleep(2 ** attempt)
                    continue

                posts = data.get("data", {}).get("children", [])
                if not posts:
                    return 0

                new_count = 0
                skipped_score = 0
                skipped_seen = 0
                skipped_blacklist = 0

                for child in posts:
                    if new_count >= budget:
                        break

                    post_data = child.get("data", {})
                    if not post_data or child.get("kind") != "t3":
                        continue

                    result = await self._process_json_post(
                        post_data, subreddit, min_score
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
                    "%d по score, %d видели, %d blacklist",
                    subreddit, len(posts), new_count,
                    skipped_score, skipped_seen, skipped_blacklist,
                )
                return new_count

            except Exception as exc:
                logger.warning(
                    "RedditMonitor: ошибка r/%s (попытка %d/%d): %s",
                    subreddit, attempt, self.max_retries, exc,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        return 0

    async def _process_json_post(
        self, post: dict, subreddit: str, min_score: int
    ) -> str:
        """
        Обрабатывает один пост из JSON API.
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
        upvote_ratio = post.get("upvote_ratio", 1.0)

        if score < min_score:
            logger.debug(
                "RedditMonitor: r/%s '%s' score=%d < %d",
                subreddit, post.get("title", "")[:40], score, min_score,
            )
            return "score"

        if upvote_ratio < 0.7 and score < min_score * 2:
            return "score"

        title = post.get("title", "").strip()
        if not title:
            return "skip"

        author = post.get("author", "")
        if author.startswith("u/"):
            author = author[2:]

        selftext = post.get("selftext", "")
        selftext = re.sub(r"<[^>]+>", "", selftext)
        selftext = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", selftext)
        selftext = selftext.strip()

        text = selftext if len(selftext) > len(title) else title

        check_text = f"{title} {text}".lower()
        for keyword in self.BLACKLIST_KEYWORDS:
            if keyword in check_text:
                self._seen_post_ids[external_id] = external_id
                logger.info(
                    "RedditMonitor: пропущен (blacklist '%s'): %s",
                    keyword, title[:60],
                )
                return "blacklist"

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

        images = []

        image_url = post.get("url", "")
        if image_url and image_url.startswith("https://i.redd.it/"):
            images.append(image_url)

        preview = post.get("preview", {})
        if preview and isinstance(preview, dict):
            images_list = preview.get("images", [])
            if images_list and isinstance(images_list, list):
                for img_data in images_list[:3]:
                    source = img_data.get("source", {})
                    img_url = source.get("url", "")
                    if img_url and img_url not in images:
                        images.append(img_url)

        img_urls = re.findall(r"https?://i\.redd\.it/\S+", text)
        for img_url in img_urls:
            if img_url not in images:
                images.append(img_url)

        images = [url.replace("&amp;", "&") for url in images]

        links = []
        all_links = re.findall(r"https?://[^\s<>\"'\)]+", text)
        for tl in all_links:
            if "redd.it" not in tl and "reddit.com" not in tl:
                links.append(tl)

        created_utc = post.get("created_utc")
        published_at = None
        if created_utc:
            try:
                dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                published_at = dt.isoformat()
            except (ValueError, OSError, TypeError):
                pass

        num_comments = post.get("num_comments", 0)

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
            published_at_source=published_at,
        )

        if msg_id:
            self._seen_post_ids[external_id] = external_id
            logger.info(
                "RedditMonitor: #%d сохранён (r/%s, score=%d, ratio=%.0f%%, comments=%d, %d симв, %d фото)",
                msg_id, subreddit, score, upvote_ratio * 100, num_comments,
                len(text), len(images),
            )
            return "saved"

        return "skip"
