"""
Модуль мониторинга Discord серверов проекта DayZ News Monitor.
Читает новые сообщения из одного канала Discord (куда приходят новости
всех нужных проектов) с помощью discord.py-self и сохраняет их в БД.
"""

import asyncio
import json
import re
from typing import Optional

from discord import (
    Client,
    Message,
    Guild,
    TextChannel,
    Intents,
)

from database import Database
from logger import logger


class DiscordMonitor(Client):
    """
    Discord-монитор на базе discord.py-self.
    Подключается к одному серверу и отслеживает указанный канал,
    куда падают новости всех нужных DayZ-проектов.
    """

    def __init__(
        self,
        db: Database,
        token: str,
        guild_id: int,
        channel_id: int,
        min_message_length: int = 20,
    ):
        intents = Intents.default()
        intents.message_content = True
        intents.guild_messages = True
        intents.guilds = True

        super().__init__(intents=intents)
        self.db = db
        self._token = token
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.min_message_length = min_message_length
        self._ready = False

        logger.info(
            "DiscordMonitor: настроен канал %d в гильдии %d",
            channel_id,
            guild_id,
        )

    async def start_monitoring(self) -> None:
        """Запускает мониторинг Discord с автоматическим переподключением."""
        logger.info("DiscordMonitor: запуск мониторинга...")
        while True:
            try:
                await self.start(self._token)
            except Exception as exc:
                logger.error(
                    "DiscordMonitor: соединение потеряно: %s. "
                    "Переподключение через 30 сек...",
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

        # Ищем нужную гильдию
        guild = self.get_guild(self.guild_id)
        if guild:
            logger.info(
                "DiscordMonitor: гильдия '%s' (id=%d) найдена",
                guild.name,
                guild.id,
            )
        else:
            logger.warning(
                "DiscordMonitor: гильдия id=%d не найдена! "
                "Бот должен быть добавлен на сервер.",
                self.guild_id,
            )
            self._ready = False
            return

        # Ищем нужный канал
        channel = guild.get_channel(self.channel_id)
        if channel:
            logger.info(
                "DiscordMonitor: канал #%s (id=%d) найден",
                channel.name,
                channel.id,
            )
            self._ready = True

            # Регистрируем источник в БД
            await self.db.register_source(
                source_type="discord",
                server_name="Discord News Aggregator",
                source_id=str(self.guild_id),
                extra={
                    "guild_name": guild.name,
                    "channel_id": str(self.channel_id),
                    "channel_name": channel.name,
                },
            )
        else:
            logger.warning(
                "DiscordMonitor: канал id=%d не найден в гильдии '%s'",
                self.channel_id,
                guild.name,
            )
            self._ready = False

    async def on_message(self, message: Message) -> None:
        """Обрабатывает новое сообщение в Discord."""
        # Игнорируем собственные сообщения
        if message.author == self.user:
            return

        # Бот не готов или ещё не инициализирован
        if not self._ready:
            return

        # Проверяем, что сообщение из нужного канала
        if not message.guild or message.guild.id != self.guild_id:
            return

        if message.channel.id != self.channel_id:
            return

        # Извлекаем данные и сохраняем
        await self._process_message(message)

    async def _process_message(self, message: Message) -> None:
        """Извлекает и сохраняет данные из сообщения Discord."""
        channel_name = ""
        if isinstance(message.channel, TextChannel):
            channel_name = message.channel.name.lower()

        # Собираем текст: контент + текст из embeds
        text_parts = []
        if message.content:
            text_parts.append(message.content)

        title_parts = []
        if message.embeds:
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

        # Фильтрация по длине (но пропускаем сообщения с вложениями)
        if len(full_text) < self.min_message_length and not message.attachments:
            logger.debug(
                "Discord: сообщение #%d слишком короткое (%d символов) — пропущено",
                message.id,
                len(full_text),
            )
            return

        # Собираем изображения
        images = []
        if message.embeds:
            for embed in message.embeds:
                if embed.image and embed.image.url:
                    images.append(embed.image.url)
                if embed.thumbnail and embed.thumbnail.url:
                    images.append(embed.thumbnail.url)
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                images.append(attachment.url)

        # Собираем ссылки из текста
        links = []
        if message.content:
            url_pattern = r"https?://[^\s<>\"']+"
            links = list(set(re.findall(url_pattern, message.content)))

        # Вложения (сохраняем как JSON)
        attachments_data = []
        for att in message.attachments:
            attachments_data.append({
                "url": att.url,
                "filename": att.filename,
                "size": att.size,
                "content_type": att.content_type,
            })

        # Дата публикации
        published_at = message.created_at.isoformat() if message.created_at else None

        # Автор
        author_name = ""
        if message.author:
            author_name = message.author.name
            # Если есть ник на сервере — используем его
            if message.guild and isinstance(message.author, type(None)):
                member = message.guild.get_member(message.author.id)
                if member and member.nick:
                    author_name = member.nick

        # Имя сервера-проекта извлекает AI-анализатор из текста новости.
        # Здесь сохраняем автора канала как "server_name" — потом AI определит
        # реальный проект из контекста сообщения.
        server_name = author_name or "Unknown Project"

        # Сохраняем в БД
        msg_id = await self.db.save_message(
            external_id=str(message.id),
            source_type="discord",
            source_id=f"{self.guild_id}:{self.channel_id}",
            server_name=server_name,
            text=full_text,
            title=title,
            channel_name=channel_name,
            author=author_name,
            images=images,
            links=links,
            attachments=attachments_data,
            published_at_source=published_at,
        )

        if msg_id:
            logger.info(
                "Discord: новость сохранена #%d (канал=%s, автор=%s, %d символов, %d фото)",
                msg_id,
                channel_name,
                author_name,
                len(full_text),
                len(images),
            )
