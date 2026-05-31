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

from logger import logger
from database import Database
from ai_analyzer import AIAnalyzer
from deduplicator import Deduplicator
from publisher import Publisher
from scheduler import Scheduler
from vk_monitor import VKMonitor
from gui_desktop import DesktopGUI, LogCapture


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

        self._shutdown_event = asyncio.Event()
        self._discord_enabled = False
        self._gui: Optional[DesktopGUI] = None
        self._log_capture: Optional[LogCapture] = None

    def load_config(self) -> None:
        """Загружает конфигурацию из JSON-файла."""
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.error("Файл конфигурации не найден: %s", self.config_path)
            sys.exit(1)

        with open(config_file, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        logger.info("Конфигурация загружена из %s", self.config_path)

    async def initialize(self) -> None:
        """Инициализирует все компоненты системы."""
        self.load_config()
        cfg = self.config

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

        # Публикация готовых сообщений
        if self.publisher:
            self.scheduler.add_interval_job(
                func=self._task_publish_pending,
                job_id="publish_pending",
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
                    await self.db.save_processed(
                        message_id=msg_id,
                        news_type=result["news_type"],
                        priority=result["priority"],
                        should_publish=result["should_publish"],
                        summary=result["summary"],
                        server_name=result.get("server_name", ""),
                        formatted_post=result.get("formatted_post", ""),
                    )
                else:
                    await self.db.save_processed(
                        message_id=msg_id,
                        news_type="other",
                        priority="low",
                        should_publish=False,
                        summary="Ошибка анализа",
                    )

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
            )

            # Обновляем статус для GUI после подключения
            original_ready = discord_monitor.on_ready

            async def on_ready_with_gui():
                await original_ready()
                if discord_monitor._ready:
                    self._gui.update_status("discord", True)
                    self._gui.update_status("discord_user", discord_monitor.user.name if discord_monitor.user else "")
                    guild = discord_monitor.get_guild(discord_monitor.guild_id)
                    self._gui.update_status("discord_guild", guild.name if guild else "")
                    channel = guild.get_channel(discord_monitor.channel_id) if guild else None
                    self._gui.update_status("discord_channel", channel.name if channel else "")

            discord_monitor.on_ready = on_ready_with_gui

            await discord_monitor.start_monitoring()
        except Exception as exc:
            logger.error("Discord-монитор остановлен с ошибкой: %s", exc)
            self._gui.update_status("discord", False)

    # =====================================================================
    # Жизненный цикл
    # =====================================================================

    async def run(self) -> None:
        """Запускает приложение."""
        logger.info("=" * 60)
        logger.info("DayZ News Monitor запускается...")
        logger.info("=" * 60)

        await self.initialize()

        # Обновляем статус для GUI (если GUI уже запущен)
        if self._gui:
            self._gui.update_status("db", self.db is not None)
            self._gui.update_status("ai", self.ai_analyzer is not None)
            self._gui.update_status("telegram", self.publisher is not None)
            self._gui.update_status("vk", self.vk_monitor is not None)

        # Запускаем планировщик
        await self.scheduler.start()

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


def run_bot_async(monitor: "DayZNewsMonitor"):
    """Запускает asyncio-цикл бота в фоновом потоке."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(monitor.run())
    except Exception as exc:
        logger.critical("Критическая ошибка бота: %s", exc, exc_info=True)


def main():
    """Главная функция — GUI в главном потоке, бот в фоне."""
    config_path = os.environ.get("DAYZ_CONFIG", "config.json")

    monitor = DayZNewsMonitor(config_path=config_path)

    # 1. Инициализация компонентов (синхронная часть — загрузка конфига)
    monitor.load_config()

    # 2. Запускаем GUI на главном потоке (требование tkinter)
    import customtkinter as ctk
    try:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
    except Exception:
        pass

    gui = DesktopGUI(
        config_path=config_path,
        log_capture=LogCapture(),
    )

    gui.root = ctk.CTk()
    gui.root.title("DayZ News Monitor")
    gui.root.geometry("900x650")
    gui.root.minsize(750, 500)
    gui.root.configure(fg_color=gui.BG)
    gui.root.protocol("WM_DELETE_WINDOW", gui._on_close)

    gui._build_ui()
    logger.addHandler(gui.log_capture)

    # 3. Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(
        target=run_bot_async,
        args=(monitor,),
        daemon=True,
        name="BotAsync",
    )
    monitor._gui = gui
    bot_thread.start()

    # 4. Запускаем цикл логов через after() и главное окно
    gui.root.after(500, gui._poll_logs)
    gui.root.mainloop()
    gui._running = False


if __name__ == "__main__":
    main()
