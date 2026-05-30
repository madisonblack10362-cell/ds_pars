"""
Модуль мониторинга Telegram-каналов проекта DayZ News Monitor.
Читает публикации из указанных каналов с помощью Telethon (userbot)
и сохраняет их в базу данных.
"""

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from telethon import TelegramClient, types
from telethon.errors import (
    ChannelPrivateError,
    ChatAdminRequiredError,
    FloodWaitError,
    SessionPasswordNeededError,
)
from telethon.tl.functions.messages import GetHistoryRequest

from database import Database
from logger import logger


class TelegramMonitor:
    """
    Монитор Telegram-каналов на базе Telethon.
    Использует userbot-сессию для чтения публикаций из каналов.
    """

    def __init__(
        self,
        db: Database,
        api_id: int,
        api_hash: str,
        channel_configs: list[dict],
        session_name: str = "dayz_monitor",
        min_message_length: int = 20,
    ):
        self.db = db
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.channel_configs = channel_configs
        self.min_message_length = min_message_length

        # client создаётся в start()
        self.client: Optional[TelegramClient] = None
        # Кэш последних ID сообщений для каждого канала
        self._last_message_ids: dict[str, int] = {}
        # Флаг работы
        self._running = False

    async def start(self) -> None:
        """Инициализирует и подключает Telethon-клиент."""
        session_path = os.path.join("database", f"{self.session_name}")

        self.client = TelegramClient(
            session_path,
            self.api_id,
            self.api_hash,
        )
        await self.client.connect()

        # Проверяем авторизацию
        me = await self.client.get_me()
        if not me:
            logger.error(
                "TelegramMonitor: не удалось авторизоваться. "
                "Запустите интерактивную авторизацию."
            )
            return

        logger.info(
            "TelegramMonitor: подключён как %s (id=%d)",
            me.first_name or me.username,
            me.id,
        )

        self._running = True

        # Предзагружаем последние сообщения из каждого канала
        await self._load_initial_state()

    async def authorize_interactive(self) -> None:
        """
        Интерактивная авторизация (для первого запуска).
        Запрашивает код и пароль у пользователя.
        """
        if not self.client:
            await self.start()

        me = await self.client.get_me()
        if me:
            logger.info("TelegramMonitor: уже авторизован")
            return

        logger.info(
            "TelegramMonitor: интерактивная авторизация. "
            "Введите код из Telegram-приложения."
        )
        await self.client.start()
        logger.info("TelegramMonitor: авторизация успешна")

    async def stop(self) -> None:
        """Отключает Telethon-клиент."""
        self._running = False
        if self.client:
            await self.client.disconnect()
            logger.info("TelegramMonitor: отключён")

    async def _load_initial_state(self) -> None:
        """
        Загружает ID последних сообщений для каждого канала,
        чтобы при первом запуске не обрабатывать старые посты.
        """
        for cfg in self.channel_configs:
            channel = cfg.get("channel", "")
            if not channel:
                continue

            try:
                entity = await self.client.get_entity(channel)
                messages = await self.client.get_messages(entity, limit=1)
                if messages:
                    self._last_message_ids[channel] = messages[0].id
                    logger.info(
                        "TelegramMonitor: канал %s, последний msg_id=%d",
                        channel,
                        messages[0].id,
                    )

                # Регистрируем источник
                await self.db.register_source(
                    source_type="telegram",
                    server_name=cfg.get("server", "Unknown"),
                    source_id=channel,
                    extra={"entity_id": entity.id if hasattr(entity, "id") else None},
                )

            except Exception as exc:
                logger.warning(
                    "TelegramMonitor: не удалось загрузить начальное состояние канала %s: %s",
                    channel,
                    exc,
                )

    async def check_all_channels(self) -> int:
        """
        Проверяет все настроенные каналы на наличие новых сообщений.

        Returns:
            Количество новых сообщений, сохранённых в БД.
        """
        if not self._running or not self.client:
            return 0

        total_new = 0
        for cfg in self.channel_configs:
            channel = cfg.get("channel", "")
            server_name = cfg.get("server", "Unknown")
            if not channel:
                continue

            count = await self._check_channel(channel, server_name)
            total_new += count

        if total_new > 0:
            logger.info(
                "TelegramMonitor: найдено %d новых сообщений во всех каналах",
                total_new,
            )
        return total_new

    async def _check_channel(self, channel: str, server_name: str) -> int:
        """Проверяет один канал на новые сообщения."""
        try:
            entity = await self.client.get_entity(channel)
        except (ChannelPrivateError, ValueError) as exc:
            logger.warning(
                "TelegramMonitor: канал %s недоступен: %s", channel, exc
            )
            return 0

        last_id = self._last_message_ids.get(channel, 0)
        new_count = 0

        try:
            # Получаем сообщения после последнего известного ID
            messages = await self.client.get_messages(
                entity,
                limit=20,
                min_id=last_id,
            )

            # Сортируем по ID (от старых к новым)
            messages = sorted(messages, key=lambda m: m.id if m else 0)

            for msg in messages:
                if msg is None or msg.id <= last_id:
                    continue

                saved = await self._process_message(msg, channel, server_name)
                if saved:
                    new_count += 1
                    self._last_message_ids[channel] = max(
                        self._last_message_ids.get(channel, 0), msg.id
                    )

        except FloodWaitError as exc:
            logger.warning(
                "TelegramMonitor: FloodWait на канале %s, ожидание %d секунд",
                channel,
                exc.seconds,
            )
            await asyncio.sleep(exc.seconds + 1)

        except Exception as exc:
            logger.error(
                "TelegramMonitor: ошибка при проверке канала %s: %s",
                channel,
                exc,
            )

        return new_count

    async def _process_message(
        self,
        msg: types.Message,
        channel: str,
        server_name: str,
    ) -> int | None:
        """Обрабатывает и сохраняет одно сообщение из Telegram."""
        # Извлекаем текст
        text = ""
        if msg.text:
            text = msg.text.strip()
        elif msg.message:
            text = msg.message.strip()

        # Фильтрация по длине
        if len(text) < self.min_message_length and not msg.media:
            return None

        # Заголовок (из grouped_id или первые строки)
        title = ""
        lines = text.split("\n")
        if lines and len(lines[0]) > 5:
            title = lines[0][:200]

        # Изображения и медиа
        images = []
        if msg.media:
            if isinstance(msg.media, (types.MessageMediaPhoto, types.Photo)):
                # Скачиваем фото и получаем URL (через Telethon)
                try:
                    photo_path = await self.client.download_media(
                        msg, file="images/tg_{id}_{hash}.jpg".format(
                            id=msg.id,
                            hash=abs(hash(channel)) % 100000,
                        )
                    )
                    if photo_path:
                        images.append(photo_path)
                except Exception as exc:
                    logger.debug(
                        "TelegramMonitor: не удалось скачать фото из %s: %s",
                        channel,
                        exc,
                    )
            elif isinstance(msg.media, types.MessageMediaWebPage):
                if msg.media.webpage and msg.media.webpage.url:
                    images.append(msg.media.webpage.url)

        # Ссылки
        links = []
        if msg.entities:
            for entity in msg.entities:
                if isinstance(entity, types.MessageEntityUrl):
                    url = text[entity.offset:entity.offset + entity.length]
                    links.append(url)
                elif isinstance(entity, types.MessageEntityTextUrl):
                    links.append(entity.url)

        # Дата публикации
        published_at = None
        if msg.date:
            published_at = msg.date.isoformat()

        # Автор
        author = ""
        if msg.forward_from:
            if hasattr(msg.forward_from, "from_id") and msg.forward_from.from_id:
                try:
                    from_user = await self.client.get_entity(msg.forward_from.from_id)
                    author = from_user.first_name or from_user.username or ""
                except Exception:
                    author = "Forwarded"
        elif msg.sender_id:
            try:
                sender = await self.client.get_entity(msg.sender_id)
                author = sender.first_name or sender.username or ""
            except Exception:
                pass

        # Сохраняем в БД
        msg_id = await self.db.save_message(
            external_id=str(msg.id),
            source_type="telegram",
            source_id=channel,
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
                "TelegramMonitor: новость #%d сохранена (канал=%s, сервер=%s)",
                msg_id,
                channel,
                server_name,
            )
            return msg_id

        return None
