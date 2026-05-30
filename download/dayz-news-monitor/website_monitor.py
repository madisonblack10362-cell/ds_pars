"""
Модуль мониторинга веб-сайтов проекта DayZ News Monitor.
Парсит HTML-страницы и RSS-ленты сайтов проектов,
извлекая новости, обновления и changelog.
"""

import asyncio
import hashlib
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from database import Database
from logger import logger


class WebsiteMonitor:
    """
    Монитор веб-сайтов DayZ-проектов.
    Поддерживает RSS и HTML-парсинг для извлечения новостей.
    """

    def __init__(
        self,
        db: Database,
        site_configs: list[dict],
        min_message_length: int = 20,
        request_timeout: int = 30,
        max_retries: int = 3,
        user_agent: str | None = None,
    ):
        self.db = db
        self.site_configs = site_configs
        self.min_message_length = min_message_length
        self.timeout = aiohttp.ClientTimeout(total=request_timeout)
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Кэш обработанных URL-адресов для отслеживания новых
        self._seen_urls: dict[str, str] = {}  # url -> external_id
        # Кэш контента для определения изменений
        self._content_hashes: dict[str, str] = {}

    async def load_initial_state(self) -> None:
        """Предзагружает кэш из базы данных."""
        messages = await self.db.get_recent_messages(hours=720, limit=500)
        for msg in messages:
            links_raw = msg.get("links", "[]")
            try:
                import json
                links = json.loads(links_raw)
                for link in links:
                    self._seen_urls[link] = msg["external_id"]
            except (json.JSONDecodeError, TypeError):
                pass

            # Хешируем контент для отслеживания изменений
            text = msg.get("text", "")
            if text:
                url_key = f"{msg['source_type']}_{msg['source_id']}_{msg['external_id']}"
                self._content_hashes[url_key] = hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest()

        logger.info(
            "WebsiteMonitor: кэш загружен (%d URL, %d хешей контента)",
            len(self._seen_urls),
            len(self._content_hashes),
        )

    async def check_all_sites(self) -> int:
        """
        Проверяет все настроенные сайты на наличие новых записей.

        Returns:
            Количество новых записей, сохранённых в БД.
        """
        total_new = 0

        for cfg in self.site_configs:
            server_name = cfg.get("server", "Unknown")
            url = cfg.get("url", "")
            rss_url = cfg.get("rss_url", "")
            custom_interval = cfg.get("check_interval_minutes", 30)

            if rss_url:
                count = await self._check_rss(server_name, rss_url, cfg)
                total_new += count

            if url:
                count = await self._check_html(server_name, url, cfg)
                total_new += count

        if total_new > 0:
            logger.info(
                "WebsiteMonitor: найдено %d новых записей на всех сайтах",
                total_new,
            )
        return total_new

    # -------------------------------------------------------------------------
    # RSS мониторинг
    # -------------------------------------------------------------------------

    async def _check_rss(
        self, server_name: str, rss_url: str, cfg: dict
    ) -> int:
        """Проверяет RSS-ленту на новые записи."""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(
                        rss_url,
                        headers={"User-Agent": self.user_agent},
                    ) as response:
                        if response.status != 200:
                            logger.warning(
                                "WebsiteMonitor: RSS %s вернул статус %d",
                                rss_url,
                                response.status,
                            )
                            return 0

                        content = await response.text()
                        feed = feedparser.parse(content)

                        if not feed.entries:
                            return 0

                        new_count = 0
                        # Обрабатываем записи от старых к новым
                        entries = list(reversed(feed.entries))

                        for entry in entries:
                            saved = await self._process_rss_entry(
                                entry, server_name, rss_url, cfg
                            )
                            if saved:
                                new_count += 1

                        return new_count

            except asyncio.TimeoutError:
                logger.warning(
                    "WebsiteMonitor: таймаут RSS %s (попытка %d/%d)",
                    rss_url,
                    attempt,
                    self.max_retries,
                )
            except Exception as exc:
                logger.warning(
                    "WebsiteMonitor: ошибка RSS %s (попытка %d/%d): %s",
                    rss_url,
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        return 0

    async def _process_rss_entry(
        self, entry: dict, server_name: str, rss_url: str, cfg: dict
    ) -> int | None:
        """Обрабатывает одну запись из RSS-ленты."""
        link = entry.get("link", "")
        title = entry.get("title", "").strip()

        if not link:
            return None

        # Проверяем, не видели ли уже этот URL
        if link in self._seen_urls:
            return None

        # Извлекаем текст
        text = ""
        summary = entry.get("summary", "")
        if summary:
            # Убираем HTML-теги из summary
            text = BeautifulSoup(summary, "lxml").get_text(strip=True)

        content = entry.get("content", [])
        if content and isinstance(content, list):
            for item in content:
                if item.get("value"):
                    full_text = BeautifulSoup(
                        item["value"], "lxml"
                    ).get_text(strip=True)
                    if len(full_text) > len(text):
                        text = full_text

        # Фильтрация
        if len(text) < self.min_message_length and len(title) < 10:
            return None

        # Изображения из медиа-контента RSS
        images = []
        media_content = entry.get("media_content", [])
        if isinstance(media_content, list):
            for media in media_content:
                if media.get("url"):
                    images.append(media["url"])

        # Также ищем изображения в enclosure
        enclosures = entry.get("enclosures", [])
        if isinstance(enclosures, list):
            for enc in enclosures:
                href = enc.get("href", "")
                if href and any(
                    ext in href.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")
                ):
                    images.append(href)

        # Ссылки
        links = []
        if link:
            links.append(link)

        # Дата
        published_at = None
        published = entry.get("published", "") or entry.get("updated", "")
        if published:
            try:
                dt = feedparser.parse(published)
                if hasattr(dt, "tm_year"):
                    published_at = datetime(
                        dt.tm_year, dt.tm_mon, dt.tm_mday,
                        dt.tm_hour, dt.tm_min, dt.tm_sec
                    ).isoformat()
            except (ValueError, TypeError):
                pass

        # Автор
        author = entry.get("author", "") or entry.get("dc_creator", "")

        # Регистрируем источник
        await self.db.register_source(
            source_type="website",
            server_name=server_name,
            source_id=cfg.get("url", rss_url),
            extra={"rss_url": rss_url},
        )

        # Формируем полный текст для сохранения
        full_text = f"{title}\n\n{text}" if title and text else (title or text)

        external_id = hashlib.sha256(
            f"rss_{link}".encode("utf-8")
        ).hexdigest()[:20]

        # Сохраняем
        msg_id = await self.db.save_message(
            external_id=external_id,
            source_type="website",
            source_id=cfg.get("url", rss_url),
            server_name=server_name,
            text=full_text,
            title=title,
            author=author,
            images=images,
            links=links,
            published_at_source=published_at,
        )

        if msg_id:
            self._seen_urls[link] = external_id
            logger.info(
                "WebsiteMonitor: RSS-новость #%d сохранена (сервер=%s, url=%s)",
                msg_id,
                server_name,
                link[:80],
            )
            return msg_id

        return None

    # -------------------------------------------------------------------------
    # HTML мониторинг
    # -------------------------------------------------------------------------

    async def _check_html(
        self, server_name: str, url: str, cfg: dict
    ) -> int:
        """Парсит HTML-страницу и извлекает новости."""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(
                        url,
                        headers={"User-Agent": self.user_agent},
                    ) as response:
                        if response.status != 200:
                            logger.warning(
                                "WebsiteMonitor: %s вернул статус %d",
                                url,
                                response.status,
                            )
                            return 0

                        html = await response.text()
                        new_count = await self._parse_html_page(
                            html, url, server_name, cfg
                        )
                        return new_count

            except asyncio.TimeoutError:
                logger.warning(
                    "WebsiteMonitor: таймаут %s (попытка %d/%d)",
                    url,
                    attempt,
                    self.max_retries,
                )
            except Exception as exc:
                logger.warning(
                    "WebsiteMonitor: ошибка %s (попытка %d/%d): %s",
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        return 0

    async def _parse_html_page(
        self, html: str, base_url: str, server_name: str, cfg: dict
    ) -> int:
        """
        Парсит HTML-страницу и извлекает статьи/новости.
        Ищет элементы article, .post, .news, .entry и т.д.
        """
        soup = BeautifulSoup(html, "lxml")

        # Ищем контейнеры новостей по селекторам
        selectors = [
            "article",
            ".post",
            ".news-item",
            ".entry",
            ".news-entry",
            ".content-post",
            "[class*='news']",
            "[class*='article']",
            "[class*='post']",
        ]

        entries = []
        for selector in selectors:
            found = soup.select(selector)
            if found:
                entries = found
                logger.debug(
                    "WebsiteMonitor: найдено %d записей по селектору '%s' на %s",
                    len(found),
                    selector,
                    base_url,
                )
                break

        if not entries:
            logger.debug(
                "WebsiteMonitor: записи не найдены на %s", base_url
            )
            return 0

        new_count = 0
        for entry in entries[:20]:  # Ограничиваем количество
            saved = await self._parse_html_entry(
                entry, base_url, server_name, cfg
            )
            if saved:
                new_count += 1

        return new_count

    async def _parse_html_entry(
        self, entry: BeautifulSoup, base_url: str, server_name: str, cfg: dict
    ) -> int | None:
        """Извлекает данные из одного HTML-элемента статьи."""
        # Заголовок
        title = ""
        title_tag = entry.find(["h1", "h2", "h3", "h4"])
        if title_tag:
            title = title_tag.get_text(strip=True)

        # Если заголовок не найден в h-тегах, ищем в классах
        if not title:
            for cls_tag in entry.select(
                ["[class*='title']", "[class*='heading']"]
            ):
                t = cls_tag.get_text(strip=True)
                if t:
                    title = t
                    break

        # Текст
        text_parts = []
        for p in entry.find_all("p"):
            p_text = p.get_text(strip=True)
            if p_text and len(p_text) > 10:
                text_parts.append(p_text)
        text = "\n".join(text_parts)

        # Ссылки
        links = []
        link_tag = entry.find("a", href=True)
        article_url = ""
        if link_tag:
            article_url = urljoin(base_url, link_tag["href"])
            links.append(article_url)

        # Все ссылки в записи
        for a in entry.find_all("a", href=True):
            href = urljoin(base_url, a["href"])
            if href.startswith("http") and href not in links:
                links.append(href)

        # Изображения
        images = []
        for img in entry.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src:
                img_url = urljoin(base_url, src)
                if img_url.startswith("http"):
                    images.append(img_url)

        # Дата
        published_at = None
        time_tag = entry.find("time")
        if time_tag:
            datetime_str = time_tag.get("datetime", "") or time_tag.get_text(strip=True)
            if datetime_str:
                published_at = self._parse_html_date(datetime_str)
        else:
            for cls_tag in entry.select(
                ["[class*='date']", "[class*='time']", "[class*='published']"]
            ):
                date_text = cls_tag.get_text(strip=True)
                if date_text:
                    published_at = self._parse_html_date(date_text)
                    if published_at:
                        break

        # Фильтрация
        full_text = f"{title}\n\n{text}" if title and text else (title or text)
        if len(full_text) < self.min_message_length:
            return None

        # Проверка на дубликат по хешу контента
        content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        cache_key = f"html_{base_url}_{content_hash[:20]}"
        if cache_key in self._content_hashes:
            return None

        external_id = hashlib.sha256(
            f"html_{base_url}_{title}_{content_hash}".encode("utf-8")
        ).hexdigest()[:20]

        # Регистрируем источник
        await self.db.register_source(
            source_type="website",
            server_name=server_name,
            source_id=base_url,
        )

        # Сохраняем
        msg_id = await self.db.save_message(
            external_id=external_id,
            source_type="website",
            source_id=base_url,
            server_name=server_name,
            text=full_text,
            title=title,
            images=images,
            links=links,
            published_at_source=published_at,
        )

        if msg_id:
            self._content_hashes[cache_key] = content_hash
            if links:
                self._seen_urls[links[0]] = external_id
            logger.info(
                "WebsiteMonitor: HTML-новость #%d сохранена (сервер=%s, url=%s)",
                msg_id,
                server_name,
                base_url[:80],
            )
            return msg_id

        return None

    @staticmethod
    def _parse_html_date(date_str: str) -> Optional[str]:
        """Пытается распарсить дату из HTML в ISO-формат."""
        if not date_str:
            return None

        date_formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d.%m.%Y",
            "%d.%m.%Y %H:%M",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]

        date_str = date_str.strip()

        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.isoformat()
            except ValueError:
                continue

        return None
