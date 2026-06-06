"""
Модуль мониторинга Reddit для DayZ News Monitor.
Парсит сабреддиты через Reddit RSS, фильтрует по рейтингу,
извлекает текст, изображения и ссылки.
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser

from database import Database
from logger import logger


# Reddit RSS URL для сабреддита (hot, new, rising)
REDDIT_RSS_URL = "https://www.reddit.com/r/{subreddit}/{sort}.rss?limit={limit}"


class RedditMonitor:
    """
    Монитор сабреддитов Reddit.
    Парсит RSS-ленту, фильтрует по минимальному рейтингу,
    извлекает текст, self-post контент, изображения и ссылки.
    """

    def __init__(
        self,
        db: Database,
        subreddit_configs: list[dict],
        min_message_length: int = 20,
        min_score: int = 50,
        request_timeout: int = 30,
        max_retries: int = 3,
        user_agent: str | None = None,
    ):
        """
        Args:
            db: Экземпляр Database.
            subreddit_configs: Список конфигов сабреддитов:
                [{"subreddit": "dayz", "sort": "hot", "min_score": 50, "limit": 25}]
            min_message_length: Минимальная длина текста для сохранения.
            min_score: Минимальный рейтинг поста (ups) по умолчанию.
            request_timeout: Таймаут HTTP-запросов в секундах.
            max_retries: Макс. количество попыток при ошибках.
            user_agent: User-Agent для запросов к Reddit.
        """
        self.db = db
        self.subreddit_configs = subreddit_configs
        self.min_message_length = min_message_length
        self.min_score = min_score
        self.timeout = aiohttp.ClientTimeout(total=request_timeout)
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "DayZNewsMonitor/1.0 (https://github.com/madisonblack10362-cell/dayz-monitor-web)"
        )

        # Кэш обработанных post_id
        self._seen_post_ids: dict[str, str] = {}  # post_id -> external_id

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
        """
        Проверяет все настроенные сабреддиты на наличие новых записей.

        Returns:
            Количество новых записей, сохранённых в БД.
        """
        total_new = 0

        for cfg in self.subreddit_configs:
            subreddit = cfg.get("subreddit", "")
            if not subreddit:
                continue

            sort_type = cfg.get("sort", "hot")
            limit = min(cfg.get("limit", 25), 100)
            min_score = cfg.get("min_score", self.min_score)

            count = await self._check_subreddit(subreddit, sort_type, limit, min_score)
            total_new += count

        if total_new > 0:
            logger.info(
                "RedditMonitor: найдено %d новых постов на всех сабреддитах",
                total_new,
            )
        return total_new

    async def _check_subreddit(
        self, subreddit: str, sort_type: str, limit: int, min_score: int
    ) -> int:
        """Проверяет один сабреддит через RSS."""
        rss_url = REDDIT_RSS_URL.format(subreddit=subreddit, sort=sort_type, limit=limit)

        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(
                        rss_url,
                        headers={"User-Agent": self.user_agent},
                    ) as response:
                        if response.status != 200:
                            logger.warning(
                                "RedditMonitor: RSS %s вернул статус %d",
                                rss_url,
                                response.status,
                            )
                            return 0

                        content = await response.text()
                        feed = feedparser.parse(content)

                        if not feed.entries:
                            return 0

                        new_count = 0
                        seen_count = 0
                        # Обрабатываем от старых к новым
                        entries = list(reversed(feed.entries))

                        for entry in entries:
                            saved = await self._process_entry(
                                entry, subreddit, min_score
                            )
                            if saved:
                                new_count += 1
                            else:
                                seen_count += 1

                        logger.info(
                            "RedditMonitor: r/%s — %d записей в RSS, %d новых, %d уже видели",
                            subreddit, len(entries), new_count, seen_count,
                        )
                        return new_count

            except asyncio.TimeoutError:
                logger.warning(
                    "RedditMonitor: таймаут RSS %s (попытка %d/%d)",
                    rss_url,
                    attempt,
                    self.max_retries,
                )
            except Exception as exc:
                logger.warning(
                    "RedditMonitor: ошибка RSS %s (попытка %d/%d): %s",
                    rss_url,
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        return 0

    async def _process_entry(
        self, entry: dict, subreddit: str, min_score: int
    ) -> int | None:
        """Обрабатывает одну запись из RSS Reddit."""
        # Извлекаем post_id из link
        link = entry.get("link", "")
        post_id = entry.get("id", "")
        if not post_id and link:
            # Reddit link: https://www.reddit.com/r/dayz/comments/1xyz...
            match = re.search(r"/comments/([a-z0-9]+)", link)
            if match:
                post_id = match.group(1)

        if not post_id:
            return None

        external_id = f"reddit_{subreddit}_{post_id}"

        # Проверяем, не видели ли уже
        if external_id in self._seen_post_ids:
            return None

        # Рейтинг (Reddit RSS не содержит score — ставим 0 и пропускаем фильтр)
        score = self._extract_score(entry)

        # Фильтрация по рейтингу — только если score удалось определить
        if score > 0 and score < min_score:
            return None

        # Заголовок
        title = entry.get("title", "").strip()
        if not title:
            return None

        # Автор
        author = entry.get("author", "").strip()
        if author.startswith("/u/"):
            author = author[3:]

        # Текст поста
        text = title
        summary = entry.get("summary", "")
        if summary:
            # Убираем HTML-теги
            from bs4 import BeautifulSoup
            clean = BeautifulSoup(summary, "lxml").get_text(strip=True)
            # Reddit self-post: summary часто содержит краткий текст поста
            # Полный текст в content
            content_list = entry.get("content", [])
            if content_list and isinstance(content_list, list):
                for item in content_list:
                    if item.get("value"):
                        full_text = BeautifulSoup(
                            item["value"], "lxml"
                        ).get_text(strip=True)
                        if len(full_text) > len(clean):
                            clean = full_text
            if clean and len(clean) > len(title):
                text = clean

        # Фильтрация по длине
        if len(text) < self.min_message_length:
            return None

        # Изображения — ищем в enclosure и в тексте
        images = []

        # Media/thumbnail из RSS
        media_thumbnail = entry.get("media_thumbnail", [])
        if media_thumbnail and isinstance(media_thumbnail, list):
            for thumb in media_thumbnail:
                url = thumb.get("url", "")
                if url and not url.endswith("/self") and not url.endswith("/default"):
                    images.append(url)

        # Links/images из enclosure
        enclosures = entry.get("enclosures", [])
        if enclosures:
            for enc in enclosures:
                enc_url = enc.get("url", "") or enc.get("href", "")
                if enc_url:
                    images.append(enc_url)

        # Извлекаем изображения из текста (Reddit inline images)
        img_urls = re.findall(r"https?://i\.redd\.it/\S+", text)
        for img_url in img_urls:
            if img_url not in images:
                images.append(img_url)

        # Извлекаем preview-изображения (обычно первые)
        if not images and summary:
            # Reddit часто включает preview URL в summary
            preview_match = re.search(r'<img[^>]+src="([^"]+)"', summary)
            if preview_match:
                preview_url = preview_match.group(1)
                if not preview_url.endswith("/self") and not preview_url.endswith("/default"):
                    images.append(preview_url)

        # Ссылки
        links = []
        if link:
            links.append(link)

        # Reddit crosspost-ссылки из текста
        text_links = re.findall(r"https?://[^\s<>\"'\)]+", text)
        for tl in text_links:
            if tl not in links and "redd.it" not in tl and "reddit.com/r/" not in tl:
                links.append(tl)

        # Дата публикации
        published_at = None
        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                published_at = dt.isoformat()
            except (ValueError, OSError):
                pass

        # Регистрируем источник
        server_name = f"r/{subreddit}"
        await self.db.register_source(
            source_type="reddit",
            server_name=server_name,
            source_id=subreddit,
            extra={"min_score": min_score},
        )

        # Сохраняем в БД
        msg_id = await self.db.save_message(
            external_id=external_id,
            source_type="reddit",
            source_id=subreddit,
            server_name=server_name,
            text=text,
            title=title,
            channel_name=subreddit,
            author=author or f"u/{author}",
            images=images,
            links=links,
            published_at_source=published_at,
        )

        if msg_id:
            self._seen_post_ids[external_id] = external_id
            logger.info(
                "RedditMonitor: пост #%d сохранён (r/%s, автор=%s, score=%d, %d символов, %d фото)",
                msg_id,
                subreddit,
                author or "unknown",
                score,
                len(text),
                len(images),
            )
            return msg_id

        return None

    def _extract_score(self, entry: dict) -> int:
        """Извлекает рейтинг поста из разных полей RSS-записи Reddit."""
        # Пробуем разные источники score
        for key in ("score", "ups", "rank"):
            val = entry.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass

        # Пробуем из summary (Reddit иногда включает score в HTML)
        summary = entry.get("summary", "")
        if summary:
            # Ищем паттерн типа "50 upvotes" или "score: 50"
            match = re.search(r"(\d+)\s*(?:upvote|ups?|score)", summary, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    pass

        return 0
