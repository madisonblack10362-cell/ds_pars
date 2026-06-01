"""
Telegram Web App Integration for DayZ News Monitor Bot
==========================================================
Добавляет кнопку Web App в Telegram бота для открытия панели управления.

Инструкция по интеграции:
1. Добавить этот файл в корень проекта бота (ds_pars/)
2. В bot.py добавить импорт и вызов setup_web_app_button()
3. В publisher.py добавить вызов send_to_web_panel() после публикации

Пример интеграции в bot.py:

    from web_app_integration import setup_web_app_button

    # После запуска бота:
    await setup_web_app_button(bot, WEB_APP_URL)
"""

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
)


async def setup_web_app_button(bot: Bot, web_app_url: str):
    """
    Устанавливает кнопку Web App в меню бота.
    Открывает панель управления напрямую из меню бота.

    Args:
        bot: Экземпляр aiogram Bot
        web_app_url: URL вашего Web App на Vercel (например: https://dayz-panel.vercel.app)
    """
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Панель управления",
                web_app=WebAppInfo(url=web_app_url),
            )
        )
        print(f"[WebApp] Кнопка 'Панель управления' установлена -> {web_app_url}")
    except Exception as e:
        print(f"[WebApp] Ошибка установки кнопки: {e}")


async def setup_commands(bot: Bot):
    """Устанавливает команды бота."""
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="panel", description="Открыть панель управления"),
        BotCommand(command="status", description="Статус мониторинга"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)
    print("[WebApp] Команды бота обновлены")


def get_web_app_keyboard(web_app_url: str) -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру с кнопкой Web App для использования в сообщениях.

    Args:
        web_app_url: URL Web App на Vercel

    Returns:
        InlineKeyboardMarkup с кнопкой Web App
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Панель управления",
                    web_app=WebAppInfo(url=web_app_url),
                )
            ]
        ]
    )
    return keyboard


def get_main_reply_keyboard(web_app_url: str = "") -> ReplyKeyboardMarkup:
    """
    Возвращает основную reply-клавиатуру бота с кнопкой Web App.

    Args:
        web_app_url: URL Web App (если не указан, кнопка Web App не добавляется)

    Returns:
        ReplyKeyboardMarkup
    """
    buttons = [
        [KeyboardButton(text="Статус мониторинга")],
    ]

    if web_app_url:
        buttons.insert(0, [KeyboardButton(text="Панель управления", web_app=WebAppInfo(url=web_app_url))])

    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    return keyboard


async def send_to_web_panel(
    news_data: dict,
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 10.0,
) -> bool:
    """
    Отправляет новость на веб-панель для модерации.

    Args:
        news_data: Словарь с данными новости:
            {
                "sourceId": "discord-channel-id",
                "externalId": "message-id",
                "serverName": "DayZ Official",
                "channelName": "announcements",
                "author": "Username",
                "title": "Server Wipe",
                "content": "Full message text",
                "summary": "AI summary",
                "formattedPost": "Formatted Telegram post",
                "newsType": "wipe|update|patch|event|maintenance|other",
                "priority": "high|medium|low",
                "images": ["url1", "url2"],
                "links": ["url1", "url2"]
            }
        web_app_url: URL веб-панели (например: https://dayz-panel.vercel.app)
        bot_api_key: API ключ для авторизации (настраивается в Vercel env BOT_API_KEY)
        timeout: Таймаут запроса в секундах

    Returns:
        True если новость успешно отправлена, False в противном случае
    """
    try:
        headers = {"Content-Type": "application/json"}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{web_app_url}/api/news",
                json=news_data,
                headers=headers,
            )

            if response.status_code in (200, 201):
                result = response.json()
                print(f"[WebApp] Новость отправлена на панель: {result.get('news_id', 'unknown')}")
                return True
            else:
                print(f"[WebApp] Ошибка отправки ({response.status_code}): {response.text}")
                return False

    except httpx.TimeoutException:
        print("[WebApp] Таймаут отправки на панель")
        return False
    except Exception as e:
        print(f"[WebApp] Ошибка отправки на панель: {e}")
        return False


async def get_moderation_status(
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 5.0,
) -> dict:
    """
    Проверяет статус модерации новостей с веб-панели.

    Args:
        web_app_url: URL веб-панели
        bot_api_key: API ключ
        timeout: Таймаут

    Returns:
        Словарь со статусами: {"pending": N, "approved": N, "rejected": N}
    """
    try:
        headers = {}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{web_app_url}/api/news?status=pending&limit=1",
                headers=headers,
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "pending": data.get("total", 0),
                    "total_pages": data.get("totalPages", 0),
                }

            return {"pending": 0, "total_pages": 0}

    except Exception as e:
        print(f"[WebApp] Ошибка проверки статуса: {e}")
        return {"pending": 0, "total_pages": 0}


async def check_publish_queue(
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 15.0,
) -> list:
    """
    Проверяет очередь публикации на веб-панели.
    Возвращает новости со статусом 'scheduled', у которых scheduledAt <= сейчас.

    Returns:
        Список новостей для публикации
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
                return data.get("queue", [])

            return []
    except Exception as e:
        print(f"[WebApp] Ошибка проверки очереди публикации: {e}")
        return []


async def mark_published_on_panel(
    news_id: str,
    web_app_url: str,
    bot_api_key: str = "",
    timeout: float = 10.0,
) -> bool:
    """
    Отмечает новость как опубликованную на веб-панели.

    Args:
        news_id: ID новости на панели
        web_app_url: URL панели
        bot_api_key: API ключ

    Returns:
        True если успешно
    """
    try:
        headers = {}
        if bot_api_key:
            headers["Authorization"] = f"Bearer {bot_api_key}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{web_app_url}/api/news/{news_id}/publish",
                headers=headers,
            )
            return response.status_code in (200, 201)
    except Exception as e:
        print(f"[WebApp] Ошибка отметки публикации: {e}")
        return False
