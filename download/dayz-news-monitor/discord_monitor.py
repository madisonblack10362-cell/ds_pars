"""
Модуль мониторинга Discord серверов проекта DayZ News Monitor.
Читает новые сообщения из указанных каналов Discord с помощью discord.py-self
и сохраняет их в базу данных.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from discord import (
    Client,
    Message,
    Guild,
    TextChannel,
    Intents,
    Embed,
)
from discord.errors import Forbidden, HTTPException

from database import Database
from logger import logger


# Каналы, которые мы отслеживаем (по умолчанию)
DEFAULT_CHANNELS = [
    "announcements",
    "updates",
    "changelog",
    "patch-notes",
    "news",
    "server-news",
    "wipe-info",
    "events",
    "admin-news",
    "development",
    "devblog",
]


class DiscordMonitor(Client):
    """
    Discord-монитор на базе discord.py-self.
    Подключается к серверам и отслеживает новые сообщения
    в указанных каналах.
    """

    def __init__(
        self,
        db: Database,
        token: str,
        server_configs: list[dict],
        min_message_length: int = 20,
    ):
        intents = Intents.default()
        intents.message_content = True
        intents.guild_messages = True
        intents.guilds = True

        super().__init__(intents=intents)
        self.db = db
        self._token = token
        self.server_configs = server_configs
        self.min_message_length = min_message_length

        # Сохраняем данные конфигурации для быстрого доступа
        # guild_id -> server_name
        self._guild_names: dict[int, str] = {}
        # guild_id -> set[channel_name]
        self._watched_channels: dict[int, set[str]] = {}

        for cfg in server_configs:
            guild_id = int(cfg.get("guild_id", 0))
            server_name = cfg.get("server", "Unknown Server")
            channels = set(cfg.get("channels", DEFAULT_CHANNELS))

            if guild_id:
                self._guild_names[guild_id] = server_name
                self._watched_channels[guild_id] = channels

        logger.info(
            "DiscordMonitor: настроено %d серверов для мониторинга",
            len(self._guild_names),
        )

    async def start_monitoring(self) -> None:
        """Запускает мониторинг Discord с автоматическим переподключением."""
        logger.info("DiscordMonitor: запуск мониторинга...")
        while True:
            try:
                await self.start(self._token)
            except Exception as exc:
                logger.error(
                    "DiscordMonitor: соединение потеряно: %s. Переподключение через 30 сек...",
                    exc,
                )
                await asyncio.sleep(30)

    async def on_ready(self) -> None:
        """Вызывается при успешном подключении к Discord."""
        logger.info(
            "DiscordMonitor: подключён как %s (%d)",
            self.user.name if self.user else "unknown",
            self.user.id if self.user else 0,
        )

        # Логируем доступные серверы
        for guild in self.guilds:
            if guild.id in self._guild_names:
                logger.info(
                    "DiscordMonitor: сервер '%s' (id=%d) найден",
                    guild.name,
                    guild.id,
                )
                # Регистрируем источники в БД
                await self.db.register_source(
                    source_type="discord",
                    server_name=self._guild_names[guild.id],
                    source_id=str(guild.id),
                    extra={"channels": list(self._watched_channels.get(guild.id, []))},
                )

        # Дополнительно запрашиваем недостающие серверы по invite
        for guild_id in self._guild_names:
            found = any(g.id == guild_id for g in self.guilds)
            if not found:
                logger.warning(
                    "DiscordMonitor: сервер с id=%d ('%s') не найден в списке гильдий",
                    guild_id,
                    self._guild_names[guild_id],
                )

    async def on_message(self, message: Message) -> None:
        """Обрабатывает новое сообщение в Discord."""
        # Игнорируем собственные сообщения
        if message.author == self.user:
            return

        # Проверяем, что сообщение из отслеживаемого сервера и канала
        if not message.guild:
            return

        guild_id = message.guild.id
        if guild_id not in self._guild_names:
            return

        channel_name = ""
        if isinstance(message.channel, TextChannel):
            channel_name = message.channel.name.lower()

        watched = self._watched_channels.get(guild_id, set())
        if channel_name not in watched:
            return

        # Извлекаем данные сообщения
        await self._process_message(message, guild_id, channel_name)

    async def _process_message(
        self,
        message: Message,
        guild_id: int,
        channel_name: str,
    ) -> None:
        """Извлекает и сохраняет данные из сообщения Discord."""
        server_name = self._guild_names.get(guild_id, "Unknown")

        # Собираем текст: контент + текст из embeds
        text_parts = []
        if message.content:
            text_parts.append(message.content)

        title_parts = []
        for embed in message.embeds:
            if embed.title:
                title_parts.append(embed.title)
            if embed.description:
                text_parts.append(embed.description)
            for field in embed.fields:
                if field.name:
                    title_parts.append(field.name)
                if field.value:
                    text_parts.append(field.value)

        full_text = "\n".join(text_parts).strip()
        title = "\n".join(title_parts).strip()

        # Фильтрация по длине
        if len(full_text) < self.min_message_length and not message.attachments:
            logger.debug(
                "Discord: сообщение #%d слишком короткое (%d символов) — пропущено",
                message.id,
                len(full_text),
            )
            return

        # Собираем изображения
        images = []
        for embed in message.embeds:
            if embed.image and embed.image.url:
                images.append(embed.image.url)
            if embed.thumbnail and embed.thumbnail.url:
                images.append(embed.thumbnail.url)
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                images.append(attachment.url)

        # Собираем ссылки
        links = []
        if message.content:
            import re
            url_pattern = r"https?://[^\s<>\"']+"
            links = list(set(re.findall(url_pattern, message.content)))

        # Вложения
        attachments = []
        for att in message.attachments:
            attachments.append({
                "url": att.url,
                "filename": att.filename,
                "size": att.size,
                "content_type": att.content_type,
            })

        # Дата публикации
        published_at = message.created_at.isoformat() if message.created_at else None

        # Автор
        author_name = message.author.name if message.author else ""

        # Сохраняем в БД
        msg_id = await self.db.save_message(
            external_id=str(message.id),
            source_type="discord",
            source_id=str(guild_id),
            server_name=server_name,
            text=full_text,
            title=title,
            channel_name=channel_name,
            author=author_name,
            images=images,
            links=links,
            attachments=attachments,
            published_at_source=published_at,
        )

        if msg_id:
            logger.info(
                "Discord: новость сохранена #%d (server=%s, channel=%s, author=%s)",
                msg_id,
                server_name,
                channel_name,
                author_name,
            )
