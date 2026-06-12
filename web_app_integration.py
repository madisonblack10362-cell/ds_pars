"""
Telegram Web App Integration for DayZ News Monitor Bot
==========================================================
Отправка новостей на веб-панель для модерации,
проверка очереди публикации и управление кнопкой бота.
"""

import html as html_module
import json
import httpx
from aiogram import Bot
from aiogram.types import (
    BotCommand,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    MenuButtonWebApp,
    ParseMode,
)
from logger import logger


async def notify_moderation(
    title: str,
    news_type: str,
    priority: str,
    source: str,
    notify_chat_ids: list[int],
    bot_token: str,
    web_panel_url: str = "",
) -> None:
    """
    Отправляет уведомление о новой новости на модерацию в Telegram.
    Используется парсерами (Workshop, Patch Notes) после отправки на веб-панель.
    """
    if not notify_chat_ids or not bot_token:
        return

    type_icons = {
        "update": "🎮", "wipe": "🔄", "patch": "🔧", "event": "📅",
        "maintenance": "🛠️", "bug": "🐛", "mod_update": "🔧", "mod": "🔧",
        "guide": "📖", "pvp": "⚔️", "story": "📖", "tip": "💡",
        "discussion": "💬", "meme": "😂", "content": "📷", "other": "📰",
    }
    priority_labels = {"high": "🔴 Высокий", "medium": "🟡 Средний", "low": "🟢 Низкий"}
    icon = type_icons.get(news_type, "📰")
    prio = priority_labels.get(priority, priority)

    safe_title = html_module.escape(title[:80])
    safe_source = html_module.escape(source)

    text = (
        f"{icon} <b>Новость на модерации</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Тип:</b> {news_type}\n"
        f"⚡ <b>Приоритет:</b> {prio}\n"
        f"📡 <b>Источник:</b> {safe_source}\n\n"
        f"💬 <i>{safe_title}</i>\n\n"
    )
    if web_panel_url:
        text += f"🔗 <a href=\"{web_panel_url}/dashboard/moderation\">Открыть модерацию</a>"

    async with httpx.AsyncClient(timeout=10) as client:
        for chat_id in notify_chat_ids:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                    },
                )
                logger.debug("Уведомление о модерации отправлено: chat_id=%d", chat_id)
            except Exception as exc:
                logger.warning("Не удалось отправить уведомление chat_id=%d: %s", chat_id, exc)


async def setup_web_app_button(bot: Bot, web_app_url: str):
    """Устанавливает кнопку Web App в меню бота."""
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Панель управления",
                web_app=WebAppInfo(url=web_app_url),
            )
        )
        logger.info("Кнопка 'Панель управления' установлена -> %s", web_app_url)
    except Exception as e:
        logger.warning("Не удалось установить кнопку панели: %s", e)


async def setup_commands(bot: Bot):
    """Устанавливает команды бота."""
    commands = [
        BotCommand(command="start", description="Запустить бота и подписаться"),
        BotCommand(command="subscribe", description="Включить рассылку"),
        BotCommand(command="unsubscribe", description="Отключить рассылку"),
        BotCommand(command="status", description="Статус мониторинга"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Команды бота обновлены")


def get_web_app_keyboard(web_app_url: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой Web App."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Панель управления",
                web_app=WebAppInfo(url=web_app_url),
            )]
        ]
    )


def get_main_reply_keyboard(web_app_url: str = "") -> ReplyKeyboardMarkup:
    """Основная reply-клавиатура бота с кнопкой Web App."""
    buttons = [[KeyboardButton(text="Статус мониторинга")]]
    if web_app_url:
        buttons.insert(0, [KeyboardButton(text="Панель управления", web_app=WebAppInfo(url=web_app_url))])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


async def send_to_web_panel(
    news_data: dict,
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 10.0,
) -> bool:
    """
    Отправляет новость на веб-панель для модерации.
    Возвращает True при успешной отправке.
    """
    url = f"{web_app_url}/api/news"

    try:
        headers = {"Content-Type": "application/json"}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        logger.info("Веб-панель: отправка новости на %s (content=%d символов)",
                     url, len(str(news_data.get("content", ""))))

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=news_data, headers=headers)

            if response.status_code in (200, 201):
                result = response.json()
                news_id = result.get('news_id', 'unknown')
                logger.info("Веб-панель: новость #%s успешно отправлена на модерацию", news_id)
                return True
            else:
                logger.error(
                    "Веб-панель: ошибка отправки (HTTP %d): %s",
                    response.status_code, response.text[:500]
                )
                return False

    except httpx.TimeoutException:
        logger.error("Веб-панель: таймаут отправки (%s)", url)
        return False
    except httpx.ConnectError as e:
        logger.error("Веб-панель: не удалось подключиться к %s — %s", url, e)
        return False
    except Exception as e:
        logger.error("Веб-панель: ошибка отправки — %s", e)
        return False


async def get_moderation_status(
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 5.0,
) -> dict:
    """Проверяет количество ожидающих модерацию новостей и их список."""
    try:
        headers = {}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{web_app_url}/api/news?status=pending&limit=10",
                headers=headers,
            )
            if response.status_code == 200:
                data = response.json()
                total = data.get("total", 0)
                items = data.get("items", data.get("news", []))
                return {"pending": total, "items": items}
            return {"pending": 0, "items": []}
    except Exception as e:
        logger.debug("Веб-панель: ошибка проверки статуса: %s", e)
        return {"pending": 0, "items": []}


async def check_publish_queue(
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 15.0,
) -> list:
    """
    Проверяет очередь публикации на веб-панели.
    Возвращает новости со статусом 'scheduled', у которых scheduledAt <= сейчас.
    """
    try:
        headers = {}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{web_app_url}/api/publish-queue",
                headers=headers,
            )
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", data.get("queue", []))
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                ready = []
                for item in items:
                    scheduled = item.get("scheduledAt")
                    if not scheduled:
                        continue
                    try:
                        sched_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                        if sched_dt <= now:
                            ready.append(item)
                    except (ValueError, TypeError):
                        continue
                return ready
            return []
    except Exception as e:
        logger.debug("Веб-панель: ошибка проверки очереди: %s", e)
        return []


async def send_log_to_panel(log_data: dict, web_app_url: str, timeout: float = 3.0) -> bool:
    """
    Отправляет лог на веб-панель. Fire-and-forget pattern —
    вызывающий код должен использовать asyncio.create_task().
    """
    url = f"{web_app_url}/api/logs"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=log_data)
            if response.status_code in (200, 201):
                return True
            else:
                logger.debug("Веб-панель: ошибка отправки лога (HTTP %d): %s",
                             response.status_code, response.text[:200])
                return False
    except Exception as e:
        logger.debug("Веб-панель: не удалось отправить лог — %s", e)
        return False


async def mark_published_on_panel(
    news_id: str,
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 10.0,
) -> bool:
    """Отмечает новость как опубликованную на веб-панели."""
    try:
        headers = {}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{web_app_url}/api/news/{news_id}/publish",
                headers=headers,
            )
            if response.status_code in (200, 201):
                logger.info("Веб-панель: новость #%s отмечена как опубликованная", news_id)
                return True
            else:
                logger.error("Веб-панель: ошибка отметки публикации #%s (HTTP %d)", news_id, response.status_code)
                return False
    except Exception as e:
        logger.error("Веб-панель: ошибка отметки публикации #%s — %s", news_id, e)
        return False
