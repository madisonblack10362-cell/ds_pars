"""
Главная точка входа проекта DayZ News Monitor.
Оркестрирует мониторинг Discord (один канал), VK-групп,
AI-анализ, дедупликацию и публикацию в Telegram-канал.
"""

import asyncio
import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

from logger import logger, add_web_panel_handler
from database import Database
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Web Panel integration (опционально — нужен httpx)
try:
    from web_app_integration import setup_web_app_button, setup_commands, send_to_web_panel, check_publish_queue, mark_published_on_panel
    HAS_WEB_PANEL = True
except ImportError:
    HAS_WEB_PANEL = False
    print("[BOT] web_app_integration.py не найден — веб-панель отключена")

from ai_analyzer import AIAnalyzer
from deduplicator import Deduplicator
from publisher import Publisher
from scheduler import Scheduler
from vk_monitor import VKMonitor
from deduplicator import Deduplicator
from publisher import Publisher
from scheduler import Scheduler
from vk_monitor import VKMonitor


class DayZNewsMonitor:
    """
    Главный класс приложения. Инициализирует все компоненты,
    настраивает планировщик и управляет жизненным циклом.

    Текущая конфигурация источников:
      - Discord: один канал, куда приходят новости всех проектов
      - VK: группы DayZ-серверов
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
        self.vk_monitor: Optional[VKMonitor] = None
        self.web_panel_url: str = ""
        self.web_panel_api_key: str = ""

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
            self.web_panel_api_key = self.config.get("bot_api_key", "")
            if self.web_panel_url:
                logger.info("Веб-панель: %s", self.web_panel_url)
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
        db_path = cfg.get("database_path", "database/dayz_news.db")
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
        if bot_token and bot_token != "YOUR_BOT_TOKEN_HERE":
            self.publisher = Publisher(
                bot_token=bot_token,
                channel_id=channel_id,
                images_dir=cfg.get("images_dir", "images"),
                max_images_per_post=cfg.get("max_images_per_post", 10),
            )
            logger.info("Publisher инициализирован (канал: %s)", channel_id)

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
        # VK мониторинг
        # -----------------------------------------------------------------
        vk_token = cfg.get("vk_access_token", "")
        vk_sources = cfg.get("sources", {}).get("vk", [])

        if vk_token and vk_token != "YOUR_VK_ACCESS_TOKEN_HERE" and vk_sources:
            self.vk_monitor = VKMonitor(
                db=self.db,
                access_token=vk_token,
                group_configs=vk_sources,
                api_version=cfg.get("vk_api_version", "5.199"),
                min_message_length=cfg.get("min_message_length", 20),
                request_timeout=cfg.get("request_timeout_seconds", 30),
                max_retries=cfg.get("max_retries", 3),
            )
            await self.vk_monitor.load_initial_state()
            logger.info("VK-монитор инициализирован (%d групп)", len(vk_sources))
        else:
            logger.info("VK-монитор отключён: не указан access token или нет групп")

        # -----------------------------------------------------------------
        # Discord мониторинг (запускается как отдельная фоновая задача)
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

        # Периодическая проверка VK-групп
        if self.vk_monitor:
            self.scheduler.add_interval_job(
                func=self._task_check_vk,
                job_id="check_vk",
                minutes=check_interval,
            )

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
        logger.info("Зарегистрированные задачи: %s", self.scheduler.get_jobs_info())

    # =====================================================================
    # Задачи планировщика
    # =====================================================================

    async def _task_check_vk(self) -> None:
        """Периодическая проверка VK-групп."""
        if not self.vk_monitor:
            return
        try:
            count = await self.vk_monitor.check_all_groups()
            if count > 0:
                logger.info("VK: обработано %d новых записей", count)
        except Exception as exc:
            logger.error("Ошибка проверки VK-групп: %s", exc)

    async def _task_analyze_messages(self) -> None:
        """AI-анализ необработанных сообщений + дедупликация."""
        if not self.ai_analyzer or not self.db:
            return
        try:
            messages = await self.db.get_unprocessed_messages(limit=20)
            if not messages:
                return

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
                result = await self.ai_analyzer.analyze(text)

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
                                        "externalId": str(msg_id),
                                        "serverName": result.get("server_name", ""),
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
                                if not success:
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
        """Публикует новости из очереди веб-панели по расписанию — рассылает юзерам."""
        if not self.publisher or not self.web_panel_url or not self.db:
            return
        try:
            queue = await check_publish_queue(
                web_app_url=self.web_panel_url,
                bot_api_key=self.web_panel_api_key,
            )
            if not queue:
                return

            # Получаем список активных подписчиков
            subscribers = await self.db.get_all_subscribers()
            if not subscribers:
                logger.info("Рассылка отменена: нет подписчиков")
                # Всё равно отмечаем как опубликованные
                for item in queue:
                    news_id = item.get('id', '')
                    await mark_published_on_panel(
                        news_id=news_id,
                        web_app_url=self.web_panel_url,
                        bot_api_key=self.web_panel_api_key,
                    )
                return

            for item in queue:
                news_id = item.get('id', '')
                text = item.get('formatted_post', '') or item.get('summary', '')
                images = item.get('images', '[]')
                if isinstance(images, str):
                    try:
                        images = json.loads(images)
                    except (json.JSONDecodeError, TypeError):
                        images = []
                url_images = [img for img in images if isinstance(img, str) and img.startswith('http')]

                if text:
                    # Рассылка всем подписчикам
                    result = await self.publisher.broadcast_to_users(
                        text=text,
                        users=subscribers,
                        image_urls=url_images if url_images else None,
                    )

                    # Отмечаем заблокировавших бота
                    for blocked_uid in result.get("blocked", []):
                        await self.db.mark_user_blocked(blocked_uid)

                    logger.info(
                        'Рассылка с панели: %s (отправлено=%d, заблокировано=%d)',
                        news_id, result.get("sent", 0), len(result.get("blocked", [])),
                    )

                    # Отмечаем новость как опубликованную на панели
                    await mark_published_on_panel(
                        news_id=news_id,
                        web_app_url=self.web_panel_url,
                        bot_api_key=self.web_panel_api_key,
                    )
        except Exception as exc:
            logger.error('Ошибка рассылки с панели: %s', exc)

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
                f"Привет, <b>{user.first_name}</b>!\n\n"
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
            return

        try:
            from discord_monitor import DiscordMonitor

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
            logger.error("Discord-монитор остановлен с ошибкой: %s", exc)

    # =====================================================================
    # Жизненный цикл
    # =====================================================================

    async def run(self) -> None:
        """Запускает приложение."""
        logger.info("=" * 60)
        logger.info("DayZ News Monitor запускается...")
        logger.info("=" * 60)

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

        logger.info("=" * 60)
        logger.info("DayZ News Monitor запущен и работает")
        logger.info("Нажмите Ctrl+C для остановки")
        logger.info("=" * 60)

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
# Точка входа
# =============================================================================


def _run_bot_thread(monitor, gui=None):
    """Фоновый поток для бота. Создаёт свой asyncio event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_and_update():
        try:
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
                if monitor.vk_monitor:
                    gui.update_status("vk", True)
                if monitor._discord_enabled:
                    gui.update_status("discord", False, "Подключение...")
                else:
                    gui.update_status("discord", False, "Токен/канал не указан")

            # Сохраняем ссылку на GUI для DiscordMonitor
            monitor.gui = gui

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
    config_path = os.environ.get("DAYZ_CONFIG", "config.json")

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
