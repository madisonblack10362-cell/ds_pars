"""
Модуль мониторинга VK-сообществ проекта DayZ News Monitor.
Получает новые записи из стен VK-групп через VK API
и сохраняет их в базу данных.
"""

import asyncio
from datetime import datetime
from typing import Optional

import aiohttp

from database import Database
from logger import logger


class VKMonitor:
    """
    Монитор VK-сообществ через VK API (wall.get).
    Периодически проверяет стены групп на новые записи.
    """

    WALL_GET_URL = "https://api.vk.com/method/wall.get"
    GROUP_INFO_URL = "https://api.vk.com/method/groups.getById"

    def __init__(
        self,
        db: Database,
        access_token: str,
        group_configs: list[dict],
        api_version: str = "5.199",
        min_message_length: int = 20,
        request_timeout: int = 30,
        max_retries: int = 3,
    ):
        self.db = db
        self.access_token = access_token
        self.api_version = api_version
        self.group_configs = group_configs
        self.min_message_length = min_message_length
        self.timeout = aiohttp.ClientTimeout(total=request_timeout)
        self.max_retries = max_retries

        # Кэш последних ID постов для каждой группы
        self._last_post_ids: dict[str, int] = {}

    async def load_initial_state(self) -> None:
        """Загружает начальное состояние — ID последних постов в каждой группе."""
        for cfg in self.group_configs:
            group_id = cfg.get("group_id", "")
            if not group_id:
                continue

            try:
                posts = await self._fetch_posts(group_id, count=1)
                if posts:
                    last_post = posts[0]
                    self._last_post_ids[group_id] = last_post.get("id", 0)
                    logger.info(
                        "VKMonitor: группа %s, последний post_id=%d",
                        group_id,
                        last_post.get("id", 0),
                    )
            except Exception as exc:
                logger.warning(
                    "VKMonitor: не удалось загрузить начальное состояние для %s: %s",
                    group_id,
                    exc,
                )

    async def check_all_groups(self) -> int:
        """
        Проверяет все настроенные группы на наличие новых записей.

        Returns:
            Количество новых записей, сохранённых в БД.
        """
        total_new = 0
        for cfg in self.group_configs:
            group_id = cfg.get("group_id", "")
            server_name = cfg.get("server", "Unknown")
            if not group_id:
                continue

            count = await self._check_group(group_id, server_name)
            total_new += count

        if total_new > 0:
            logger.info(
                "VKMonitor: найдено %d новых записей во всех группах",
                total_new,
            )
        return total_new

    async def _check_group(self, group_id: str, server_name: str) -> int:
        """Проверяет одну группу на новые записи."""
        try:
            posts = await self._fetch_posts(group_id, count=20)
        except Exception as exc:
            logger.error(
                "VKMonitor: ошибка получения записей из %s: %s", group_id, exc
            )
            return 0

        if not posts:
            return 0

        last_id = self._last_post_ids.get(group_id, 0)
        new_count = 0

        # Сортируем по ID (от старых к новым)
        posts = sorted(posts, key=lambda p: p.get("id", 0))

        for post in posts:
            post_id = post.get("id", 0)

            # Пропускаем уже обработанные
            if post_id <= last_id:
                continue

            # Игнорируем репосты (копии других записей)
            if post.get("copy_history"):
                # Но проверяем — если есть оригинальный текст, тоже сохраняем
                copy_text = ""
                for item in post["copy_history"]:
                    if item.get("text"):
                        copy_text = item["text"]
                if not post.get("text") and copy_text:
                    post["_copy_text"] = copy_text

            saved = await self._process_post(post, group_id, server_name)
            if saved:
                new_count += 1
                self._last_post_ids[group_id] = max(
                    self._last_post_ids.get(group_id, 0), post_id
                )

        return new_count

    async def _fetch_posts(
        self, group_id: str, count: int = 20
    ) -> list[dict]:
        """
        Получает записи со стены группы через VK API.

        Args:
            group_id: ID группы (с минусом для групп: -12345678).
            count: Количество запрашиваемых записей (макс. 100).

        Returns:
            Список записей (dict) или пустой список.
        """
        params = {
            "owner_id": group_id,
            "count": min(count, 100),
            "filter": "all",
            "access_token": self.access_token,
            "v": self.api_version,
            "extended": 0,
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(
                        self.WALL_GET_URL, params=params
                    ) as response:
                        if response.status != 200:
                            body = await response.text()
                            logger.error(
                                "VK API вернул статус %d: %s",
                                response.status,
                                body[:500],
                            )
                            continue

                        data = await response.json()
                        if data.get("error"):
                            error_code = data["error"].get("error_code", 0)
                            error_msg = data["error"].get("error_msg", "")
                            logger.error(
                                "VK API error %d: %s", error_code, error_msg
                            )
                            return []

                        items = data.get("response", {}).get("items", [])
                        return items

            except asyncio.TimeoutError:
                logger.warning(
                    "VKMonitor: таймаут запроса (попытка %d/%d)",
                    attempt,
                    self.max_retries,
                )
            except Exception as exc:
                logger.warning(
                    "VKMonitor: ошибка запроса (попытка %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(2 ** attempt)

        return []

    async def _process_post(
        self, post: dict, group_id: str, server_name: str
    ) -> int | None:
        """Обрабатывает и сохраняет одну запись со стены VK."""
        # Извлекаем текст
        text = post.get("text", "").strip()
        if not text and post.get("_copy_text"):
            text = post["_copy_text"].strip()

        # Фильтрация по длине
        if len(text) < self.min_message_length and not post.get("attachments"):
            return None

        # Заголовок
        title = ""
        lines = text.split("\n")
        if lines and len(lines[0]) > 5:
            title = lines[0][:200]

        # Изображения
        images = []
        attachments = post.get("attachments", [])
        for att in attachments:
            att_type = att.get("type", "")
            if att_type == "photo":
                photo_data = att.get("photo", {})
                sizes = photo_data.get("sizes", [])
                # Берём самое большое изображение (тип 'w' или 'z' или 'y' или 'x')
                best_size = None
                for size in sizes:
                    if best_size is None or size.get("width", 0) > best_size.get("width", 0):
                        best_size = size
                if best_size and best_size.get("url"):
                    images.append(best_size["url"])

            # Ссылки
            if att_type == "link":
                link_data = att.get("link", {})
                if link_data.get("url"):
                    images.append(link_data["url"])

        # Ссылки из текста
        links = []
        import re
        url_pattern = r"https?://[^\s<>\"']+"
        links = list(set(re.findall(url_pattern, text)))

        # Дата публикации
        published_at = None
        timestamp = post.get("date")
        if timestamp:
            try:
                dt = datetime.fromtimestamp(timestamp, tz=None)
                published_at = dt.isoformat()
            except (ValueError, OSError):
                pass

        # Автор
        author = ""
        from_id = post.get("from_id")
        if from_id:
            author = str(from_id)

        # Регистрируем источник
        await self.db.register_source(
            source_type="vk",
            server_name=server_name,
            source_id=group_id,
        )

        # Сохраняем в БД
        msg_id = await self.db.save_message(
            external_id=f"vk_{group_id}_{post.get('id', 0)}",
            source_type="vk",
            source_id=group_id,
            server_name=server_name,
            text=text,
            title=title,
            author=author,
            images=images,
            links=links,
            published_at_source=published_at,
        )

        if msg_id:
            logger.info(
                "VKMonitor: новость #%d сохранена (группа=%s, сервер=%s)",
                msg_id,
                group_id,
                server_name,
            )
            return msg_id

        return None
