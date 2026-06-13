"""
Главная точка входа проекта DayZ News Monitor.
Оркестрирует мониторинг Discord (один канал),
AI-анализ, дедупликацию и публикацию в Telegram-канал.
"""

import asyncio
import html as html_module
import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from logger import logger, add_web_panel_handler
from database import Database
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Web Panel integration (опционально — нужен httpx)
try:
    from web_app_integration import setup_web_app_button, setup_commands, send_to_web_panel, check_publish_queue, mark_published_on_panel, get_moderation_status
    HAS_WEB_PANEL = True
except ImportError:
    HAS_WEB_PANEL = False
    print("[BOT] web_app_integration.py не найден — веб-панель отключена")

from ai_analyzer import AIAnalyzer
from deduplicator import Deduplicator
from publisher import Publisher
from scheduler import Scheduler
from steam_workshop_monitor import run_workshop_monitor, fetch_popular_mods
from patch_notes_monitor import run_patch_monitor, fetch_steam_news
from youtube_monitor import run_youtube_monitor



class DayZNewsMonitor:
    """
    Главный класс приложения. Инициализирует все компоненты,
    настраивает планировщик и управляет жизненным циклом.

    Текущая конфигурация источников:
      - Discord: один канал, куда приходят новости всех проектов
      - Telegram: только публикация (отправка в канал через bot API)
    """

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config: dict = {}
        self.db: Optional[Database] = None
        self.ai_analyzer: Optional[AIAnalyzer] = None
        self.deduplicator: Optional[Deduplicator] = None
        self.publisher: Optional[Publisher] = None
        self.scheduler: Optional[Scheduler] = None
        self.youtube_task: Optional[asyncio.Task] = None
        self._workshop_task: Optional[asyncio.Task] = None
        self._patch_task: Optional[asyncio.Task] = None
        self.web_panel_url: str = ""
        self.web_panel_api_key: str = ""
        self.notify_chat_id: str = ""
        self.moderation_notifications: bool = True
        self._last_pending_count: int = 0

        self._shutdown_event = asyncio.Event()
        self._discord_enabled = False

    def load_config(self) -> None:
        """Загружает конфигурацию из JSON-файла."""
        config_file = Path(self.config_path).resolve()
        if not config_file.exists():
            print(f"[BOT] Файл конфигурации не найден: {config_file}")
            print(f"[BOT] Текущая директория: {os.getcwd()}")
            logger.error("Файл конфигурации не найден: %s", config_file)
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            logger.info("Конфигурация загружена из %s (%d ключей)", config_file, len(self.config))

            # Web Panel URL и API ключ
            self.web_panel_url = self.config.get("web_panel_url", "")
            self.web_panel_api_key = self.config.get("web_panel_api_key", "")
            self.notify_chat_id = str(self.config.get("telegram_notify_chat_id", ""))
            self.moderation_notifications = self.config.get("moderation_notifications", True)
            if self.web_panel_url:
                logger.info("Веб-панель: %s", self.web_panel_url)
            if self.notify_chat_id:
                logger.info("Уведомления будут отправляться в чат %s", self.notify_chat_id)
        except Exception as e:
            print(f"[BOT] Ошибка чтения конфига: {e}")
            logger.error("Ошибка чтения конфига: %s", e)

    async def initialize(self) -> None:
        """Инициализирует все компоненты системы."""
        self.load_config()
        cfg = self.config

        # Add web panel log forwarding handler
        if self.web_panel_url:
            try:
                add_web_panel_handler(self.web_panel_url)
            except Exception as e:
                logger.warning("Не удалось включить пересылку логов на панель: %s", e)

        # -----------------------------------------------------------------
        # База данных
        # -----------------------------------------------------------------
        db_path = cfg.get("database_path", os.path.join(PROJECT_ROOT, "database", "dayz_news.db"))
        self.db = Database(db_path)
        await self.db.connect()
        await self.db.init_tables()
        logger.info("База данных инициализирована")

        # -----------------------------------------------------------------
        # AI-анализатор
        # -----------------------------------------------------------------
        openai_key = cfg.get("openai_api_key", "")
        if openai_key and openai_key != "YOUR_OPENAI_API_KEY_HERE":
            self.ai_analyzer = AIAnalyzer(
                api_key=openai_key,
                base_url=cfg.get("openai_base_url", "https://api.openai.com/v1"),
                model=cfg.get("openai_model", "gpt-4o-mini"),
                max_retries=cfg.get("max_retries", 3),
                timeout=cfg.get("request_timeout_seconds", 30),
            )
            logger.info(
                "AI-анализатор инициализирован (модель: %s)",
                cfg.get("openai_model", "gpt-4o-mini"),
            )
        else:
            logger.warning("AI-анализатор отключён: не указан API-ключ")

        # -----------------------------------------------------------------
        # Дедупликатор
        # -----------------------------------------------------------------
        self.deduplicator = Deduplicator(
            db=self.db,
            ai_analyzer=self.ai_analyzer,
            similarity_threshold=cfg.get("similarity_threshold", 0.85),
        )
        await self.deduplicator.warm_cache()

        # -----------------------------------------------------------------
        # Publisher (публикация в Telegram через bot API)
        # -----------------------------------------------------------------
        bot_token = cfg.get("telegram_bot_token", "")
        channel_id = cfg.get("telegram_channel_id", "")
        news_channel_id = cfg.get("telegram_news_channel_id", "")
        if bot_token and bot_token != "YOUR_BOT_TOKEN_HERE":
            self.publisher = Publisher(
                bot_token=bot_token,
                channel_id=channel_id,
                news_channel_id=news_channel_id,
                images_dir=cfg.get("images_dir", os.path.join(PROJECT_ROOT, "images")),
                max_images_per_post=cfg.get("max_images_per_post", 10),
            )
            logger.info("Publisher инициализирован (сводки: %s, новости: %s)",
                        channel_id, news_channel_id or channel_id)

            # Кнопка Web App в меню бота + команды
            if HAS_WEB_PANEL and self.web_panel_url:
                try:
                    bot_for_web = self.publisher.bot
                    await setup_web_app_button(bot_for_web, self.web_panel_url)
                    await setup_commands(bot_for_web)
                    logger.info("Кнопка панели управления и команды добавлены")
                except Exception as e:
                    logger.warning("Не удалось установить кнопку/команды панели: %s", e)

            # Регистрируем роутер для обработки команд бота
            self._setup_bot_commands()
        else:
            logger.warning("Publisher отключён: не указан токен Telegram-бота")

        # -----------------------------------------------------------------
        # YouTube монитор v2 (только ручные каналы, популярные шортсы, модерация)
        # -----------------------------------------------------------------
        if cfg.get("youtube_enabled", True):
            youtube_interval = int(cfg.get("youtube_interval_hours", 2))

            self.youtube_task = asyncio.create_task(
                run_youtube_monitor(
                    db=self.db,
                    ai_analyzer=self.ai_analyzer,
                    check_interval_hours=youtube_interval,
                    shutdown_event=self._shutdown_event,
                    publisher=self.publisher,
                    config=cfg,
                )
            )
            logger.info("YouTube монитор v2 запущен (интервал: %dч, только ручные каналы, модерация)", youtube_interval)
        else:
            logger.info("YouTube монитор отключён")

        # -----------------------------------------------------------------
        # Steam Workshop монитор
        # -----------------------------------------------------------------
        if cfg.get("workshop_enabled", True):
            workshop_interval = cfg.get("workshop_interval_hours", 1) * 3600
            workshop_min_subs = cfg.get("workshop_min_subscriptions", 100)
            steam_api_key = cfg.get("steam_api_key", "") or None

            # Список chat_id для уведомлений о модерации
            _ws_notify_ids = None
            if self.moderation_notifications and self.notify_chat_id:
                try:
                    _ws_notify_ids = [int(self.notify_chat_id)]
                except (ValueError, TypeError):
                    pass
            _ws_bot_token = cfg.get("telegram_bot_token", "")

            self._workshop_task = asyncio.create_task(
                run_workshop_monitor(
                    telegram_bot=self.publisher,
                    db=self.db,
                    ai_analyzer=self.ai_analyzer,
                    web_panel_url=self.web_panel_url,
                    web_panel_api_key=self.web_panel_api_key,
                    steam_api_key=steam_api_key,
                    check_interval=workshop_interval,
                    min_subscriptions=workshop_min_subs,
                    ai_analyze=bool(self.ai_analyzer),
                    notify_chat_ids=_ws_notify_ids,
                    telegram_bot_token=_ws_bot_token,
                )
            )
            logger.info("Steam Workshop монитор запущен (интервал: %d ч)", cfg.get("workshop_interval_hours", 1))
        else:
            logger.info("Steam Workshop монитор отключён")

        # -----------------------------------------------------------------
        # Патчноуты монитор
        # -----------------------------------------------------------------
        if cfg.get("patchnotes_enabled", False):
            patch_interval = cfg.get("patchnotes_interval_minutes", 720) * 60

            _pn_notify_ids = None
            if self.moderation_notifications and self.notify_chat_id:
                try:
                    _pn_notify_ids = [int(self.notify_chat_id)]
                except (ValueError, TypeError):
                    pass
            _pn_bot_token = cfg.get("telegram_bot_token", "")

            self._patch_task = asyncio.create_task(
                run_patch_monitor(
                    telegram_bot=self.publisher,
                    db=self.db,
                    ai_analyzer=self.ai_analyzer,
                    web_panel_url=self.web_panel_url,
                    web_panel_api_key=self.web_panel_api_key,
                    check_interval=patch_interval,
                    ai_analyze=bool(self.ai_analyzer),
                    notify_chat_ids=_pn_notify_ids,
                    telegram_bot_token=_pn_bot_token,
                )
            )
            logger.info("Патчноуты монитор запущен (интервал: %d мин)", cfg.get("patchnotes_interval_minutes", 720))
        else:
            logger.info("Патчноуты монитор отключён")

        # -----------------------------------------------------------------
        discord_token = cfg.get("discord_token", "")
        discord_cfg = cfg.get("sources", {}).get("discord", {})

        if (
            discord_token
            and discord_token != "YOUR_DISCORD_TOKEN_HERE"
            and discord_cfg.get("guild_id")
            and discord_cfg.get("channel_id")
        ):
            self._discord_enabled = True
            logger.info(
                "Discord-монитор: гильдия=%s, канал=%s — будет запущен",
                discord_cfg.get("guild_id"),
                discord_cfg.get("channel_id"),
            )
        else:
            logger.info("Discord-монитор отключён: не указан токен или нет guild/channel")

        # -----------------------------------------------------------------
        # Планировщик
        # -----------------------------------------------------------------
        self.scheduler = Scheduler()
        check_interval = cfg.get("check_interval_minutes", 5)

        # AI-анализ необработанных сообщений
        if self.ai_analyzer:
            self.scheduler.add_interval_job(
                func=self._task_analyze_messages,
                job_id="analyze_messages",
                minutes=2,
            )

        # Публикация готовых сообщений — ОТКЛЮЧЕНА.
        # Теперь все новости идут через модерацию на веб-панели.
        # _task_publish_pending зарезервирован, но не активирован.
        # if self.publisher:
        #     self.scheduler.add_interval_job(
        #         func=self._task_publish_pending,
        #         job_id="publish_pending",
        #         minutes=1,
        #     )

        # Проверка очереди публикации с веб-панели (по расписанию)
        if HAS_WEB_PANEL and self.web_panel_url and self.publisher:
            self.scheduler.add_interval_job(
                func=self._task_publish_from_panel,
                job_id="publish_from_panel",
                minutes=1,
            )

        # Проверка ожидающих модерацию новостей
        if HAS_WEB_PANEL and self.web_panel_url and self.moderation_notifications and self.notify_chat_id:
            self.scheduler.add_interval_job(
                func=self._task_check_pending_moderation,
                job_id="check_pending_moderation",
                minutes=5,
            )

        # Ежедневная сводка
        summary_hour = cfg.get("daily_summary_hour", 10)
        summary_minute = cfg.get("daily_summary_minute", 0)
        if self.publisher:
            self.scheduler.add_cron_job(
                func=self._task_daily_summary,
                job_id="daily_summary",
                hour=summary_hour,
                minute=summary_minute,
            )

        # Очистка старых данных (каждые 24 часа)
        self.scheduler.add_interval_job(
            func=self._task_cleanup,
            job_id="cleanup",
            minutes=1440,
        )

        logger.info("Все компоненты инициализированы")

        # Красивый вывод задач планировщика
        jobs = self.scheduler.get_jobs_info()
        logger.info("─── Планировщик задач ───")
        task_names = {
            "check_discord": "Discord мониторинг",
            "workshop": "Steam Workshop",
            "patchnotes": "Патчноуты",
            "analyze_messages": "AI-анализ сообщений",
            "publish_from_panel": "Публикация с панели",
            "check_pending_moderation": "Проверка модерации",
            "daily_summary": "Ежедневная сводка",
            "cleanup": "Очистка базы данных",
        }
        for job_id, schedule in jobs.items():
            name = task_names.get(job_id, job_id)
            logger.info("  ⏱  %-28s %s", name, schedule)
        logger.info("──────────────────────────")
        if self.moderation_notifications:
            logger.info("Уведомления о модерации: включены")

    # =====================================================================
    # Задачи планировщика
    # =====================================================================

    async def _get_admin_chat_ids(self) -> list[int]:
        """Возвращает список chat_id всех зарегистрированных пользователей бота."""
        if not self.db:
            return []
        try:
            users = await self.db.get_all_subscribers()
            return [u["user_id"] for u in users if u.get("user_id")]
        except Exception as exc:
            logger.warning("Не удалось получить список пользователей: %s", exc)
            return []

    async def _youtube_notify_wrapper(self, video: dict) -> None:
        """Обёртка: youtube_monitor передаёт dict, а _notify_moderation ждёт 4 аргумента.
        Работает аналогично Discord-новостям: уведомление админу о модерации."""
        title = video.get("title", "")
        category = video.get("category", "other")
        priority = "low"
        if category in ("updates", "events", "weapons", "secrets"):
            priority = "medium"
        channel = video.get("channel_title", "YouTube")
        await self._notify_moderation(
            title=title,
            news_type=category,
            priority=priority,
            source=f"YouTube: {channel}",
        )

    async def _notify_moderation(
        self, title: str, news_type: str, priority: str, source: str
    ) -> None:
        """Отправляет уведомление о новой новости на модерацию всем админам бота."""
        if not self.moderation_notifications or not self.publisher:
            return

        # Получаем список chat_id из базы бота
        admin_ids = await self._get_admin_chat_ids()
        if not admin_ids:
            # Фоллбэк: если в базе никого нет — берём из config
            if self.notify_chat_id:
                admin_ids = [int(self.notify_chat_id)]
            else:
                return

        type_icons = {
            "update": "🎮", "wipe": "🔄", "patch": "🔧", "event": "📅",
            "maintenance": "🛠️", "bug": "🐛", "mod": "🔧", "guide": "📖",
            "story": "📖", "tip": "💡", "discussion": "💬", "meme": "😂",
            "content": "📷", "other": "📰",
        }
        priority_labels = {"high": "🔴 Высокий", "medium": "🟡 Средний", "low": "🟢 Низкий"}
        icon = type_icons.get(news_type, "📰")
        prio = priority_labels.get(priority, priority)

        # Экранируем динамические данные для Telegram HTML
        safe_title = html_module.escape(title[:80])
        safe_source = html_module.escape(source)
        safe_type = html_module.escape(news_type)
        safe_prio = html_module.escape(prio)

        text = (
            f"{icon} <b>Новость на модерации</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Тип:</b> {safe_type}\n"
            f"⚡ <b>Приоритет:</b> {safe_prio}\n"
            f"📡 <b>Источник:</b> {safe_source}\n\n"
            f"💬 <i>{safe_title}</i>\n\n"
            f"🔗 <a href=\"{self.web_panel_url}/dashboard/moderation\">Открыть модерацию</a>"
        )

        for chat_id in admin_ids:
            try:
                await self.publisher.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                )
                logger.debug("Уведомление о модерации отправлено: chat_id=%d", chat_id)
            except Exception as exc:
                logger.warning("Не удалось отправить уведомление chat_id=%d: %s", chat_id, exc)

    async def _task_check_pending_moderation(self) -> None:
        """Периодически проверяет веб-панель на наличие ожидающих модерацию новостей."""
        if not self.moderation_notifications or not self.web_panel_url or not HAS_WEB_PANEL:
            return
        if not self.publisher:
            return
        try:
            status = await get_moderation_status(
                self.web_panel_url,
                bot_api_key=self.web_panel_api_key,
            )
            pending = status.get("pending", 0)

            if pending > 0 and pending > self._last_pending_count:
                # Отправляем отдельное уведомление по каждой новой новости
                items = status.get("items", [])
                new_items = items[:pending - self._last_pending_count]
                admin_ids = await self._get_admin_chat_ids()
                for item in new_items:
                    title = item.get("summary", item.get("content", "Без описания"))[:80]
                    news_type = item.get("newsType", item.get("news_type", "other"))
                    priority = item.get("priority", "medium")
                    source = item.get("source", item.get("source_type", "unknown"))
                    await self._notify_moderation(title, news_type, priority, source)
            self._last_pending_count = pending
        except Exception as exc:
            logger.debug("Ошибка проверки модерации: %s", exc)

    async def _task_analyze_messages(self) -> None:
        """AI-анализ необработанных сообщений + дедупликация."""
        if not self.ai_analyzer or not self.db:
            return
        try:
            # Берём максимум 3 за раз — чтобы не спамить пачками
            messages = await self.db.get_unprocessed_messages(limit=3)
            if not messages:
                return

            processed_count = 0
            for msg in messages:
                msg_id = msg["id"]
                text = msg.get("text", "")

                # Дедупликация
                if self.deduplicator:
                    try:
                        images = json.loads(msg.get("images", "[]"))
                    except (json.JSONDecodeError, TypeError):
                        images = []

                    duplicate_of = await self.deduplicator.is_duplicate(
                        msg_id, text, images
                    )

                    if duplicate_of:
                        await self.deduplicator.mark_as_duplicate(
                            duplicate_of, msg_id
                        )
                        continue

                # AI-анализ
                author = msg.get("author", "") or msg.get("server_name", "")
                source_type = msg.get("source_type", "")
                result = None

                if source_type == "youtube":
                    # YouTube контент уже обработан монитором с AI и отправлен на панель
                    continue
                else:
                    result = await self.ai_analyzer.analyze(text, author=author)

                if result:
                    # Всегда сохраняем с should_publish=False в локальной БД,
                    # чтобы авто-публикатор _task_publish_pending не публиковал
                    # новости без модерации. Публикация — ТОЛЬКО после одобрения
                    # через веб-панель.
                    await self.db.save_processed(
                        message_id=msg_id,
                        news_type=result["news_type"],
                        priority=result["priority"],
                        should_publish=False,
                        summary=result["summary"],
                        server_name=result.get("server_name", ""),
                        formatted_post=result.get("formatted_post", ""),
                    )

                    logger.info(
                        "Сообщение #%d отправлено на модерацию (type=%s, priority=%s)",
                        msg_id, result["news_type"], result["priority"],
                    )

                    # Отправить на веб-панель для модерацию
                    if HAS_WEB_PANEL:
                        if not self.web_panel_url:
                            logger.warning("Веб-панель: URL не настроен в config.json (web_panel_url)")
                        else:
                            try:
                                success = await send_to_web_panel(
                                    news_data={
                                        "sourceId": source_type or "discord",
                                        "externalId": str(msg_id),
                                        "serverName": result.get("server_name", "") or author,
                                        "content": text,
                                        "summary": result.get("summary", ""),
                                        "formattedPost": result.get("formatted_post", ""),
                                        "newsType": result.get("news_type", "other"),
                                        "priority": result.get("priority", "low"),
                                        "images": json.loads(msg.get("images", "[]")) if msg.get("images") else [],
                                    },
                                    web_app_url=self.web_panel_url,
                                    bot_api_key=self.web_panel_api_key or None,
                                )
                                if success:
                                    await self._notify_moderation(
                                        title=result.get("summary", "")[:80],
                                        news_type=result.get("news_type", "other"),
                                        priority=result.get("priority", "low"),
                                        source=result.get("server_name", "") or author,
                                    )
                                elif not success:
                                    logger.error("Веб-панель: не удалось отправить новость #%d", msg_id)
                            except Exception as web_err:
                                logger.error("Веб-панель: исключение при отправке #%d: %s", msg_id, web_err)
                    else:
                        logger.warning("Веб-панель: модуль web_app_integration не загружен")
                else:
                    await self.db.save_processed(
                        message_id=msg_id,
                        news_type="other",
                        priority="low",
                        should_publish=False,
                        summary="Ошибка анализа",
                    )
                    # Всё равно отправляем на веб-панель как черновик
                    if HAS_WEB_PANEL and self.web_panel_url:
                        try:
                            await send_to_web_panel(
                                news_data={
                                    "sourceId": msg.get("source_type", "discord"),
                                    "externalId": str(msg_id),
                                    "serverName": "",
                                    "content": text,
                                    "summary": "",
                                    "formattedPost": "",
                                    "newsType": "other",
                                    "priority": "low",
                                    "images": json.loads(msg.get("images", "[]")) if msg.get("images") else [],
                                },
                                web_app_url=self.web_panel_url,
                                bot_api_key=self.web_panel_api_key or None,
                            )
                        except Exception as web_err:
                            logger.warning("Веб-панель: ошибка отправки черновика: %s", web_err)

        except Exception as exc:
            logger.error("Ошибка AI-анализа: %s", exc)

    async def _task_publish_pending(self) -> None:
        """Публикация сообщений, готовых к отправке."""
        if not self.publisher or not self.db:
            return
        try:
            pending = await self.db.get_pending_publish(limit=10)
            if not pending:
                return

            for msg in pending:
                await self._publish_single(msg)

        except Exception as exc:
            logger.error("Ошибка публикации: %s", exc)

    async def _publish_single(self, msg: dict) -> None:
        """Публикует одно сообщение в Telegram-канал."""
        msg_id = msg["id"]

        # Приоритет: используем AI-отформатированный пост, если есть
        formatted_post = msg.get("formatted_post", "")
        ai_server = msg.get("ai_server_name", "")

        if formatted_post:
            # AI уже подготовила готовый пост — используем его
            text = formatted_post
        else:
            # Fallback: форматируем через шаблон publisher
            server = ai_server or msg.get("server_name", "Unknown")
            text = self.publisher.format_post(
                server_name=server,
                news_type=msg.get("news_type", "other"),
                priority=msg.get("priority", "low"),
                summary=msg.get("summary", ""),
                original_text=msg.get("text", ""),
                published_at=msg.get("published_at_source"),
                author=msg.get("author", ""),
                links=self._parse_json_field(msg.get("links", "[]")),
            )

        # Извлекаем изображения
        images = self._parse_json_field(msg.get("images", "[]"))
        url_images = [img for img in images if img.startswith("http")]

        # Публикуем
        tg_msg_id = await self.publisher.publish_message(
            text=text,
            image_urls=url_images if url_images else None,
        )

        if tg_msg_id:
            await self.db.mark_published(
                message_id=msg_id,
                telegram_message_id=tg_msg_id,
                publish_format=msg.get("news_type", ""),
            )

    async def _task_publish_from_panel(self) -> None:
        """Публикует новости из очереди веб-панели по расписанию."""
        if not self.publisher or not self.web_panel_url:
            return
        try:
            queue = await check_publish_queue(
                web_app_url=self.web_panel_url,
                bot_api_key=self.web_panel_api_key,
            )
            for item in queue:
                news_id = item.get('id', '')
                formatted_post = item.get('formattedPost', '') or item.get('formatted_post', '')
                summary = item.get('summary', '') or item.get('content', '')
                text = formatted_post or summary

                images_raw = item.get('images', '[]')
                if isinstance(images_raw, str):
                    try:
                        images = json.loads(images_raw)
                    except (json.JSONDecodeError, TypeError):
                        images = []
                else:
                    images = images_raw if isinstance(images_raw, list) else []

                valid_images = [img for img in images if isinstance(img, str) and (img.startswith('http') or img.startswith('data:'))]

                # ── YouTube: ищем скачанный видео-файл вместо thumbnail ──
                video_paths = None
                is_youtube = False
                source_type = item.get('sourceType', '') or item.get('source_type', '')
                external_id = item.get('externalId', '') or item.get('external_id', '')

                if source_type == 'youtube' and external_id and external_id.startswith('yt_'):
                    is_youtube = True
                    yt_video_id = external_id[3:]  # убираем "yt_" префикс
                    video_file = self._find_youtube_downloaded_file(yt_video_id)
                    if video_file:
                        video_paths = [video_file]
                        valid_images = []  # видео replaces thumbnail
                        logger.info('YouTube публикация: видео-файл найден %s -> %s', yt_video_id, video_file)
                    else:
                        # Файл не найден — пробуем скачать прямо сейчас
                        logger.info('YouTube публикация: файл не найден, скачиваю %s...', yt_video_id)
                        try:
                            from youtube_monitor import download_short_by_id
                            dl_path = await download_short_by_id(yt_video_id)
                            if dl_path:
                                video_paths = [dl_path]
                                valid_images = []
                                logger.info('YouTube публикация: скачан %s -> %s', yt_video_id, dl_path)
                            else:
                                logger.error('YouTube публикация: НЕ удалось скачать видео %s — публикация ОТМЕНЕНА', yt_video_id)
                        except Exception as dl_err:
                            logger.error('YouTube публикация: ошибка скачивания %s: %s — публикация ОТМЕНЕНА', yt_video_id, dl_err)

                # ── YouTube без видео — НЕ публикуем ──
                if is_youtube and not video_paths:
                    logger.error('ПРОПУСК YouTube новости %s: видео не найдено и не скачалось', news_id)
                    continue

                if text:
                    logger.info('Публикация с панели: id=%s, video=%s, images=%d, text_len=%d',
                                news_id, 'YES' if video_paths else 'no',
                                len(valid_images), len(text))
                    tg_msg_id = await self.publisher.publish_message(
                        text=text,
                        image_urls=valid_images if valid_images else None,
                        video_paths=video_paths,
                    )
                    if tg_msg_id:
                        await mark_published_on_panel(
                            news_id=news_id,
                            web_app_url=self.web_panel_url,
                            bot_api_key=self.web_panel_api_key,
                        )
                        logger.info('Опубликовано с панели: %s', news_id)
                    else:
                        logger.error('Ошибка публикации с панели: %s — Telegram не вернул msg_id', news_id)
                else:
                    logger.warning('Пропуск публикации: id=%s — пустой текст', news_id)
        except Exception as exc:
            logger.error('Ошибка публикации из очереди панели: %s', exc)

    @staticmethod
    def _find_youtube_downloaded_file(video_id: str) -> str | None:
        """
        Ищет скачанный видео-файл для YouTube видео по video_id.
        Сначала проверяет youtube_moderation.json (там сохраняется downloaded_file),
        потом ищет файл напрямую в downloads/.
        """
        import os

        # 1) Проверяем локальную очередь модерации
        try:
            mod_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'youtube_moderation.json')
            if os.path.exists(mod_file):
                with open(mod_file, 'r', encoding='utf-8') as f:
                    queue = json.load(f)
                for entry in queue:
                    if entry.get('video_id') == video_id:
                        dl = entry.get('downloaded_file', '')
                        if dl and os.path.isfile(dl):
                            return dl
                        break
        except Exception:
            pass

        # 2) Ищем файл напрямую в downloads/
        for downloads_sub in ['downloads', os.path.join('downloads', 'youtube')]:
            downloads_dir = os.path.join(PROJECT_ROOT, downloads_sub)
            if not os.path.isdir(downloads_dir):
                continue
            for ext in ('mp4', 'webm', 'mkv', '3gp'):
                candidate = os.path.join(downloads_dir, f'{video_id}.{ext}')
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    return candidate

        return None

    async def _task_daily_summary(self) -> None:
        """Публикует ежедневную сводку."""
        if not self.publisher or not self.db:
            return

        try:
            stats = await self.db.get_daily_stats(hours=24)
            events = await self.db.get_daily_events(hours=24)

            high_count = stats.get("high_count", 0) or 0
            medium_count = stats.get("medium_count", 0) or 0

            logger.info(
                "Ежедневная сводка: high=%d, medium=%d, events=%d",
                high_count,
                medium_count,
                len(events),
            )

            await self.publisher.publish_daily_summary(
                high_count=high_count,
                medium_count=medium_count,
                events=events,
            )

        except Exception as exc:
            logger.error("Ошибка публикации ежедневной сводки: %s", exc)

    def _setup_bot_commands(self) -> None:
        """Настраивает aiogram роутер для обработки команд от юзеров бота."""
        from aiogram import Dispatcher
        self._dp = Dispatcher()
        self._bot_router = Router()
        self._dp.include_router(self._bot_router)

        @self._bot_router.message(CommandStart())
        async def cmd_start(message: Message):
            user = message.from_user
            if not user:
                return
            await self.db.register_bot_user(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name or "",
            )
            sub_count = await self.db.get_subscriber_count()
            await message.answer(
                f"Привет, <b>{html_module.escape(user.first_name or '')}</b>!\n\n"
                f"Я бот мониторинга DayZ новостей.\n"
                f"После модерации новости будут приходить прямо тебе в личку.\n\n"
                f"Ты автоматически подписан на рассылку.\n"
                f"Подписчиков: {sub_count}\n\n"
                f"<b>Команды:</b>\n"
                f"/subscribe — включить рассылку\n"
                f"/unsubscribe — отключить рассылку\n"
                f"/help — помощь\n"
                f"/status — статус мониторинга",
                parse_mode=ParseMode.HTML,
            )

        @self._bot_router.message(Command("subscribe"))
        async def cmd_subscribe(message: Message):
            user = message.from_user
            if not user:
                return
            await self.db.register_bot_user(user.id, user.username or "", user.first_name or "")
            await self.db.subscribe_user(user.id)
            await message.answer(
                "Рассылка включена. Новость будет приходить тебе в личку после модерации."
            )

        @self._bot_router.message(Command("unsubscribe"))
        async def cmd_unsubscribe(message: Message):
            user = message.from_user
            if not user:
                return
            await self.db.register_bot_user(user.id, user.username or "", user.first_name or "")
            await self.db.unsubscribe_user(user.id)
            await message.answer("Рассылка отключена.")

        @self._bot_router.message(Command("help"))
        async def cmd_help(message: Message):
            await message.answer(
                "<b>DayZ News Monitor</b>\n\n"
                "<b>Команды:</b>\n"
                "/start — запуск бота и подписка\n"
                "/subscribe — включить рассылку\n"
                "/unsubscribe — отключить рассылку\n"
                "/help — эта справка\n"
                "/status — статус мониторинга\n\n"
                "Новости собираются из Discord, проходят AI-анализ и модерацию, "
                "затем приходят тебе в личку по расписанию.",
                parse_mode=ParseMode.HTML,
            )

        @self._bot_router.message(Command("status"))
        async def cmd_status(message: Message):
            if not self.db or not self.publisher:
                await message.answer("Бот не полностью инициализирован.")
                return
            sub_count = await self.db.get_subscriber_count()
            is_sub = await self.db.is_user_subscribed(message.from_user.id if message.from_user else 0)
            status_text = (
                f"<b>Статус мониторинга</b>\n\n"
                f"Подписчиков: {sub_count}\n"
                f"Ты: {'подписан' if is_sub else 'не подписан'}\n"
                f"Discord: {'работает' if self._discord_enabled else 'выключен'}\n"
                f"AI: {'работает' if self.ai_analyzer else 'выключен'}\n"
            )
            await message.answer(status_text, parse_mode=ParseMode.HTML)

        logger.info("Обработчики команд бота зарегистрированы (/start, /subscribe, /unsubscribe, /help, /status)")

    async def _task_cleanup(self) -> None:
        """Очищает старые записи из базы данных."""
        if not self.db:
            return

        try:
            await self.db._connection.execute(
                """DELETE FROM messages
                   WHERE collected_at < datetime('now', '-30 days')
                     AND id IN (SELECT message_id FROM processed_messages)"""
            )
            await self.db._connection.execute(
                """DELETE FROM messages
                   WHERE collected_at < datetime('now', '-14 days')
                     AND id NOT IN (SELECT message_id FROM processed_messages)"""
            )
            await self.db._connection.execute(
                """DELETE FROM logs WHERE created_at < datetime('now', '-14 days')"""
            )
            await self.db._connection.commit()
            logger.info("Очистка старых данных выполнена")
        except Exception as exc:
            logger.error("Ошибка очистки данных: %s", exc)

    # =====================================================================
    # Discord-монитор (отдельная фоновая задача)
    # =====================================================================

    async def _run_discord_monitor(self) -> None:
        """Запускает Discord-монитор как отдельную корутину."""
        if not self._discord_enabled:
            logger.info("Discord-монитор: отключён в настройках, пропуск")
            return

        logger.info("Discord-монитор: ожидание 60 сек перед запуском...")
        await asyncio.sleep(60)  # Задержка после старта бота

        try:
            from discord_monitor import DiscordMonitor
        except Exception as e:
            logger.error(
                "Discord-монитор: не удалось загрузить модуль: %s", e,
                exc_info=True,
            )
            return

        logger.info("Discord-монитор: модуль загружен, запуск...")

        try:
            discord_cfg = self.config.get("sources", {}).get("discord", {})

            discord_monitor = DiscordMonitor(
                db=self.db,
                token=self.config["discord_token"],
                guild_id=int(discord_cfg["guild_id"]),
                channel_id=int(discord_cfg["channel_id"]),
                min_message_length=self.config.get("min_message_length", 20),
                gui=self.gui,
            )
            await discord_monitor.start_monitoring()
        except Exception as exc:
            logger.error("Discord-монитор остановлен с ошибкой: %s", exc, exc_info=True)

    # =====================================================================
    # Жизненный цикл
    # =====================================================================

    BANNER = r"""
  ╔══════════════════════════════════════════════╗
  ║        🧟  DayZ News Monitor  v2.0            ║
  ║     Новости DayZ → AI → Telegram + Web Panel    ║
  ╚══════════════════════════════════════════════╝
"""

    async def run(self) -> None:
        """Запускает приложение."""
        print(self.BANNER)

        await self.initialize()

        # Запускаем планировщик
        await self.scheduler.start()

        # Запускаем Telegram polling для обработки команд юзеров
        if self.publisher and hasattr(self, '_dp'):
            asyncio.create_task(self._run_bot_polling())

        # Запускаем Discord-монитор в фоне
        if self._discord_enabled:
            asyncio.create_task(self._run_discord_monitor())

        # Graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._shutdown(s)),
                )
            except NotImplementedError:
                pass

        logger.info("Bot is running. Нажмите Ctrl+C для остановки.")

        await self._shutdown_event.wait()
        await self._cleanup()

    async def _shutdown(self, signal_received) -> None:
        """Обрабатывает сигнал завершения."""
        sig_name = (
            signal_received.name
            if hasattr(signal_received, "name")
            else str(signal_received)
        )
        logger.info("Получен сигнал %s. Завершение работы...", sig_name)
        self._shutdown_event.set()

    async def _run_bot_polling(self) -> None:
        """Запускает aiogram polling для обработки команд бота (/start, /subscribe и т.д.)."""
        try:
            logger.info("Telegram polling запущен — бот принимает команды юзеров")
            await self._dp.start_polling(self.publisher.bot)
        except Exception as exc:
            logger.error("Telegram polling остановлен с ошибкой: %s", exc)

    async def _cleanup(self) -> None:
        """Освобождает ресурсы при завершении."""
        logger.info("Очистка ресурсов...")

        if self.scheduler:
            await self.scheduler.stop()
        if self.publisher:
            await self.publisher.close()
        if self._workshop_task:
            self._workshop_task.cancel()
        if self._patch_task:
            self._patch_task.cancel()
        if self.db:
            await self.db.close()

        logger.info("DayZ News Monitor остановлен")

    @staticmethod
    def _parse_json_field(raw: str) -> list:
        """Безопасно парсит JSON-поле из БД."""
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, TypeError):
            return []


# =============================================================================
# Периодическое обновление GUI
# =============================================================================

async def _periodic_gui_update(monitor, gui, interval=30):
    """
    Каждые interval секунд обновляет счётчики на дашборде
    и статусную строку источников.
    """
    import os as _os

    while not monitor._shutdown_event.is_set():
        try:
            await asyncio.sleep(interval)

            if not monitor.db:
                continue

            # Счётчики из БД
            stats = await monitor.db.get_daily_stats(hours=24)
            total = stats.get("total", 0) or 0
            published = stats.get("published_count", 0) or 0

            # high + medium = проанализированные (с приоритетом)
            analyzed = (stats.get("high_count", 0) or 0) + (stats.get("medium_count", 0) or 0) + (stats.get("low_count", 0) or 0)

            # Дубликаты: собранные минус уникальные
            cursor = await monitor.db._connection.execute(
                "SELECT COUNT(*) FROM messages WHERE collected_at >= datetime('now', '-24 hours')"
            )
            row = await cursor.fetchone()
            messages = row[0] if row else 0

            # Считаем дубликаты (сообщения без processed записей)
            cursor2 = await monitor.db._connection.execute(
                """SELECT COUNT(*) FROM messages m
                   LEFT JOIN processed_messages pm ON m.id = pm.message_id
                   WHERE m.collected_at >= datetime('now', '-24 hours')
                   AND pm.message_id IS NULL"""
            )
            row2 = await cursor2.fetchone()
            duplicates = row2[0] if row2 else 0

            gui.update_counters(
                messages=messages,
                analyzed=analyzed,
                published=published,
                duplicates=duplicates,
            )

            # Статусная строка источников
            parts = []
            if monitor.youtube_task and not monitor.youtube_task.done():
                parts.append(f"YouTube: работает (каждые {monitor.config.get('youtube_interval_hours', 2)}ч)")
            elif monitor.youtube_task and monitor.youtube_task.done():
                parts.append("YouTube: остановлен")

            # Cookies статус для YouTube
            cookies_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "cookies.txt")
            if _os.path.isfile(cookies_path):
                parts.append("YouTube cookies: загружены")
            else:
                parts.append("YouTube cookies: не найден (cookies.txt)")

            if monitor._workshop_task and not monitor._workshop_task.done():
                parts.append(f"Workshop: работает")
            elif monitor._workshop_task and monitor._workshop_task.done():
                parts.append("Workshop: остановлен")

            if monitor._patch_task and not monitor._patch_task.done():
                parts.append("Патчноуты: работают")
            elif monitor._patch_task and monitor._patch_task.done():
                parts.append("Патчноуты: остановлены")

            if parts:
                gui.update_source_detail("  |  ".join(parts))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Ошибка обновления GUI счётчиков: %s", e)


# =============================================================================
# Точка входа
# =============================================================================


def _run_bot_thread(monitor, gui=None):
    """Фоновый поток для бота. Создаёт свой asyncio event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_and_update():
        try:
            # Сразу показываем что бот запускается
            if gui:
                gui.set_status_starting()
            await monitor.initialize()
            # Обновляем GUI статусы после инициализации
            if gui:
                gui.set_status_running()
                if monitor.db:
                    gui.update_status("db", True, "SQLite подключена")
                if monitor.ai_analyzer:
                    gui.update_status("ai", True, monitor.config.get("openai_model", ""))
                else:
                    gui.update_status("ai", False, "API ключ не указан")
                if monitor.publisher:
                    gui.update_status("telegram", True, monitor.config.get("telegram_channel_id", ""))
                else:
                    gui.update_status("telegram", False, "Токен не указан")
                if monitor.youtube_task:
                    gui.update_status("youtube", True, f"каждые {monitor.config.get('youtube_interval_hours', 2)}ч")
                else:
                    gui.update_status("youtube", False, "Отключён")
                if monitor._workshop_task:
                    gui.update_status("workshop", True, f"каждые {monitor.config.get('workshop_interval_hours', 1)} ч")
                else:
                    gui.update_status("workshop", False, "Отключён")
                if monitor._patch_task:
                    gui.update_status("patchnotes", True, f"каждые {monitor.config.get('patchnotes_interval_minutes', 720)} мин")
                else:
                    gui.update_status("patchnotes", False, "Отключён")
                if monitor._discord_enabled:
                    gui.update_status("discord", False, "Подключение...")
                else:
                    gui.update_status("discord", False, "Токен/канал не указан")

            # Сохраняем ссылку на GUI для DiscordMonitor
            monitor.gui = gui

            # Периодическое обновление счётчиков и статуса источников
            if gui and monitor.db:
                asyncio.create_task(_periodic_gui_update(monitor, gui))

            await monitor.scheduler.start()

            # Запускаем Telegram polling для команд юзеров
            if monitor.publisher and hasattr(monitor, '_dp'):
                asyncio.create_task(monitor._run_bot_polling())

            if monitor._discord_enabled:
                asyncio.create_task(monitor._run_discord_monitor())

            gui_root_method = None
            try:
                gui_root_method = monitor.run_no_wait
            except Exception:
                pass

            if gui_root_method:
                await gui_root_method()
            else:
                await monitor._shutdown_event.wait()

            await monitor._cleanup()
        except Exception as exc:
            logger.critical("Критическая ошибка в потоке бота: %s", exc, exc_info=True)

    try:
        loop.run_until_complete(run_and_update())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.critical("Критическая ошибка в потоке бота: %s", exc, exc_info=True)
    finally:
        loop.close()


def main():
    """
    GUI в главном потоке, бот в фоновом.
    """
    config_path = os.environ.get("DAYZ_CONFIG", os.path.join(PROJECT_ROOT, "config.json"))

    monitor = DayZNewsMonitor(config_path=config_path)
    monitor.load_config()

    try:
        from gui_desktop import DesktopGUI, LogCapture

        log_capture = LogCapture()
        logger.addHandler(log_capture)

        gui = DesktopGUI(
            config_path=config_path,
            log_capture=log_capture,
            bot_instance=monitor,
        )

        # Бот в фоновом потоке, GUI передаётся для обновления статусов
        bot_thread = threading.Thread(
            target=_run_bot_thread,
            args=(monitor, gui),
            daemon=True,
        )
        bot_thread.start()

        # GUI в главном потоке
        gui.run()

    except ImportError:
        print("[MAIN] gui_desktop.py не найден")
        try:
            asyncio.run(monitor.run())
        except KeyboardInterrupt:
            pass
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logger.critical("Критическая ошибка: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
