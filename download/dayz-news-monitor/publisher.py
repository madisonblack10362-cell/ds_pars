"""
Модуль публикации новостей в Telegram-канал проекта DayZ News Monitor.
Форматирует новости согласно приоритету и отправляет через aiogram 3.x.
"""

import json
import os
from datetime import datetime
from typing import Optional

from aiogram import Bot, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InputMediaPhoto, FSInputFile

from logger import logger

# Соответствие типов новостей и иконок
NEWS_TYPE_ICONS = {
    "wipe": "\u26a0\ufe0f ВАЙП",
    "update": "\U0001f525 ОБНОВЛЕНИЕ",
    "server_open": "\U0001f7e2 ОТКРЫТИЕ СЕРВЕРА",
    "new_season": "\U0001f31f НОВЫЙ СЕЗОН",
    "event": "\U0001f3af ИВЕНТ",
    "maintenance": "\U0001f527 ТЕХРАБОТЫ",
    "balance_change": "\u2696\ufe0f БАЛАНС",
    "economy_change": "\U0001f4b0 ЭКОНОМИКА",
    "content_add": "\u2728 НОВЫЙ КОНТЕНТ",
    "bugfix": "\U0001f527 ИСПРАВЛЕНИЯ",
    "map_change": "\U0001f5fa\ufe0f КАРТА",
    "transport_change": "\U0001f697 ТРАНСПОРТ",
    "loot_change": "\U0001f4e6 ЛУТ",
    "mod_update": "\U0001f504 МОДЫ",
    "server_merge": "\U0001f500 СЛИЯНИЕ",
    "char_transfer": "\U0001f680 ПЕРЕНОС",
    "important_announcement": "\U0001f4e2 АНОНС",
    "recruitment": "\U0001f4bc НАБОР",
    "other": "\U0001f4cb НОВОСТЬ",
}

PRIORITY_ICONS = {
    "high": "\U0001f534",
    "medium": "\U0001f7e1",
    "low": "\u26aa",
}

# Хештеги для типов новостей
NEWS_TYPE_HASHTAGS = {
    "wipe": "#вайп",
    "update": "#обновление",
    "server_open": "#открытие",
    "new_season": "#сезон",
    "event": "#ивент",
    "maintenance": "#техработы",
    "balance_change": "#баланс",
    "economy_change": "#экономика",
    "content_add": "#контент",
    "bugfix": "#исправления",
    "map_change": "#карта",
    "transport_change": "#транспорт",
    "loot_change": "#лут",
    "mod_update": "#моды",
    "server_merge": "#слияние",
    "char_transfer": "#перенос",
    "important_announcement": "#анонс",
}


class Publisher:
    """Публикует проанализированные новости в Telegram-канал."""

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        images_dir: str = "images",
        max_images_per_post: int = 10,
    ):
        self.channel_id = channel_id
        self.images_dir = images_dir
        self.max_images_per_post = max_images_per_post

        os.makedirs(images_dir, exist_ok=True)

        self.bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        logger.info("Publisher инициализирован. Канал: %s", channel_id)

    async def close(self) -> None:
        """Закрывает сессию бота."""
        await self.bot.session.close()
        logger.info("Publisher: сессия бота закрыта")

    def format_post(
        self,
        server_name: str,
        news_type: str,
        priority: str,
        summary: str,
        original_text: str = "",
        published_at: str | None = None,
        author: str = "",
        links: list[str] | None = None,
    ) -> str:
        """
        Форматирует текст поста для Telegram согласно шаблону.

        Args:
            server_name: Название сервера/проекта.
            news_type: Тип новости.
            priority: Приоритет (high/medium/low).
            summary: Краткое резюме от LLM.
            original_text: Оригинальный текст новости.
            published_at: Дата публикации в источнике.
            author: Автор новости.
            links: Ссылки, связанные с новостью.

        Returns:
            Отформатированный текст для отправки в Telegram.
        """
        # Заголовок с иконкой типа новости
        type_label = NEWS_TYPE_ICONS.get(news_type, "\U0001f4cb НОВОСТЬ")
        priority_icon = PRIORITY_ICONS.get(priority, "")

        # Формируем дату
        date_str = ""
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%d %B %Y").lower()
            except (ValueError, AttributeError):
                date_str = published_at[:10] if published_at else ""

        lines = []
        lines.append(f"{priority_icon} <b>{type_label}</b>")
        lines.append("")
        lines.append(f"\U0001f3ae Сервер: <b>{server_name}</b>")

        if date_str:
            lines.append(f"\U0001f4c5 Дата: {date_str}")

        if author:
            lines.append(f"\U0001f464 От: {author}")

        lines.append("")

        # Резюме
        if summary:
            lines.append(f"<i>{summary}</i>")
            lines.append("")

        # Основные изменения (из оригинального текста — берём первые 1000 символов)
        if original_text and len(original_text) > len(summary):
            trimmed = original_text[:1000]
            # Разбиваем на строки и форматируем
            paragraphs = [p.strip() for p in trimmed.split("\n") if p.strip()]
            lines.append("Подробнее:")
            for para in paragraphs[:10]:
                lines.append(f"\u2022 {para}")

        # Ссылки
        if links:
            lines.append("")
            for link in links[:3]:
                lines.append(f"\U0001f517 {link}")

        # Хештеги
        hashtags = ["#dayz", "#новости"]
        type_tag = NEWS_TYPE_HASHTAGS.get(news_type)
        if type_tag:
            hashtags.append(type_tag)
        lines.append("")
        lines.append(" ".join(hashtags))

        return "\n".join(lines)

    def format_daily_summary(
        self,
        high_count: int,
        medium_count: int,
        events: list[dict],
    ) -> str:
        """
        Форматирует ежедневную сводку новостей.

        Args:
            high_count: Количество новостей высокого приоритета.
            medium_count: Количество новостей среднего приоритета.
            events: Список событий для сводки.

        Returns:
            Отформатированный текст сводки.
        """
        lines = []
        lines.append("\U0001f4ca <b>СВОДКА DAYZ</b>")
        lines.append("")
        lines.append("За последние сутки:")
        lines.append("")
        lines.append(f"\U0001f534 Важных новостей: <b>{high_count}</b>")
        lines.append(f"\U0001f7e1 Средних новостей: <b>{medium_count}</b>")
        lines.append("")

        if events:
            lines.append("<b>Главные события:</b>")
            lines.append("")
            for event in events[:10]:
                server = event.get("server_name", "Неизвестно")
                news_type = event.get("news_type", "other")
                summary = event.get("summary", "")
                type_label = NEWS_TYPE_ICONS.get(news_type, "\U0001f4cb")

                line = f"\u2022 {type_label} <b>{server}</b>"
                if summary:
                    line += f" — {summary}"
                lines.append(line)
        else:
            lines.append("За сутки значимых событий не обнаружено.")

        lines.append("")
        lines.append("#dayz #новости #сводка")
        return "\n".join(lines)

    async def publish_message(
        self,
        text: str,
        image_paths: list[str] | None = None,
        image_urls: list[str] | None = None,
    ) -> Optional[int]:
        """
        Публикует сообщение в Telegram-канал.

        Args:
            text: Текст сообщения.
            image_paths: Локальные пути к изображениям.
            image_urls: URL-адреса изображений для скачивания.

        Returns:
            ID отправленного сообщения в Telegram или None при ошибке.
        """
        # Собираем изображения для отправки
        local_images: list[str] = list(image_paths or [])

        # Скачиваем изображения по URL, если есть
        if image_urls:
            downloaded = await self._download_images(image_urls)
            local_images.extend(downloaded)

        # Ограничиваем количество изображений
        local_images = local_images[: self.max_images_per_post]

        try:
            if local_images:
                return await self._send_with_images(text, local_images)
            else:
                msg = await self.bot.send_message(
                    chat_id=self.channel_id, text=text
                )
                logger.info(
                    "Сообщение опубликовано (без фото): TG msg_id=%d",
                    msg.message_id,
                )
                return msg.message_id
        except Exception as exc:
            logger.error("Ошибка публикации в Telegram: %s", exc)
            # Попытка отправить без изображений
            try:
                msg = await self.bot.send_message(
                    chat_id=self.channel_id, text=text
                )
                logger.warning(
                    "Сообщение опубликовано без фото (fallback): TG msg_id=%d",
                    msg.message_id,
                )
                return msg.message_id
            except Exception as fallback_exc:
                logger.error("Fallback-публикация также не удалась: %s", fallback_exc)
                return None

    async def _send_with_images(
        self, text: str, image_paths: list[str]
    ) -> Optional[int]:
        """
        Отправляет сообщение с медиагруппой изображений.
        Если изображений несколько — создаёт медиагруппу (album).
        """
        import aiofiles

        # Подготавливаем InputMedia-объекты
        from aiogram.types import InputMediaPhoto

        if not image_paths:
            return None

        media_group = []
        for path in image_paths:
            try:
                if os.path.exists(path) and os.path.isfile(path):
                    photo = InputMediaPhoto(media=FSInputFile(path))
                    media_group.append(photo)
            except Exception as exc:
                logger.warning("Не удалось прикрепить изображение %s: %s", path, exc)

        if not media_group:
            # Нет валидных изображений — отправляем только текст
            msg = await self.bot.send_message(chat_id=self.channel_id, text=text)
            return msg.message_id

        try:
            if len(media_group) == 1:
                # Одно изображение — отправляем с подписью
                msg = await self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=media_group[0].media,
                    caption=text,
                )
                logger.info(
                    "Сообщение опубликовано (1 фото): TG msg_id=%d",
                    msg.message_id,
                )
                return msg.message_id
            else:
                # Несколько изображений — медиагруппа
                # Текст — в подписи первого фото, остальные без подписи
                media_group[0].caption = text
                media_group[0].parse_mode = ParseMode.HTML
                messages = await self.bot.send_media_group(
                    chat_id=self.channel_id,
                    media=media_group,
                )
                logger.info(
                    "Сообщение опубликовано (%d фото): TG msg_id=%d",
                    len(media_group),
                    messages[0].message_id,
                )
                return messages[0].message_id
        except Exception as exc:
            logger.error("Ошибка отправки медиагруппы: %s", exc)
            # Fallback — текст без фото
            msg = await self.bot.send_message(chat_id=self.channel_id, text=text)
            return msg.message_id

    async def _download_images(self, urls: list[str]) -> list[str]:
        """
        Скачивает изображения по URL-адресам и сохраняет локально.
        Возвращает список путей к скачанным файлам.
        """
        import aiohttp
        import aiofiles

        downloaded: list[str] = []

        async with aiohttp.ClientSession() as session:
            for url in urls[:self.max_images_per_post]:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status != 200:
                            continue

                        # Определяем расширение файла
                        content_type = resp.headers.get("Content-Type", "")
                        if "png" in content_type:
                            ext = ".png"
                        elif "gif" in content_type:
                            ext = ".gif"
                        elif "webp" in content_type:
                            ext = ".webp"
                        else:
                            ext = ".jpg"

                        # Генерируем имя файла
                        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{abs(hash(url)) % 100000}{ext}"
                        filepath = os.path.join(self.images_dir, filename)

                        # Сохраняем файл
                        content = await resp.read()
                        async with aiofiles.open(filepath, "wb") as f:
                            await f.write(content)

                        downloaded.append(filepath)
                        logger.debug("Изображение скачано: %s -> %s", url, filepath)

                except Exception as exc:
                    logger.warning("Не удалось скачать изображение %s: %s", url, exc)

        return downloaded

    async def publish_daily_summary(
        self,
        high_count: int,
        medium_count: int,
        events: list[dict],
    ) -> Optional[int]:
        """
        Публикует ежедневную сводку в Telegram-канал.

        Returns:
            ID отправленного сообщения или None.
        """
        text = self.format_daily_summary(high_count, medium_count, events)
        return await self.publish_message(text)



