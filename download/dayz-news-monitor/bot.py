"""
Главная точка входа проекта DayZ News Monitor.
Оркестрирует все модули: мониторинг, анализ, дедупликацию и публикацию.
"""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from logger import logger
from database import Database
from ai_analyzer import AIAnalyzer
from deduplicator import Deduplicator
from publisher import Publisher
from scheduler import Scheduler
from telegram_monitor import TelegramMonitor
from vk_monitor import VKMonitor
from website_monitor import WebsiteMonitor


class DayZNewsMonitor:
    """
    Главный класс приложения. Инициализирует все компоненты,
    настраивает планировщик и управляет жизненным циклом.
    """

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config: dict = {}
        self.db: Optional[Database] = None
        self.ai_analyzer: Optional[AIAnalyzer] = None
        self.deduplicator: Optional[Deduplicator] = None
        self.publisher: Optional[Publisher] = None
        self.scheduler: Optional[Scheduler] = None
        self.tg_monitor: Optional[TelegramMonitor] = None
        self.vk_monitor: Optional[VKMonitor] = None
        self.website_monitor: Optional[WebsiteMonitor] = None

        # Флаг для graceful shutdown
        self._shutdown_event = asyncio.Event()
        # Флаги активности мониторов (зависят от наличия токенов в конфиге)
        self._discord_enabled = False
        self._telegram_monitor_enabled = False

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
            logger.info("AI-анализатор инициализирован (модель: %s)", cfg.get("openai_model", "gpt-4o-mini"))
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
        # Publisher (публикация в Telegram)
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
        # Мониторинг Telegram-каналов (через Telethon userbot)
        # -----------------------------------------------------------------
        tg_api_id = cfg.get("telegram_api_id", 0)
        tg_api_hash = cfg.get("telegram_api_hash", "")
        tg_session = cfg.get("telegram_session_name", "dayz_monitor")
        tg_sources = cfg.get("sources", {}).get("telegram", [])

        if (
            tg_api_id
            and tg_api_hash
            and tg_api_hash != "YOUR_API_HASH_HERE"
            and tg_sources
        ):
            self.tg_monitor = TelegramMonitor(
                db=self.db,
                api_id=tg_api_id,
                api_hash=tg_api_hash,
                channel_configs=tg_sources,
                session_name=tg_session,
                min_message_length=cfg.get("min_message_length", 20),
            )
            try:
                await self.tg_monitor.start()
                if self.tg_monitor.client and await self.tg_monitor.client.get_me():
                    self._telegram_monitor_enabled = True
                    logger.info("Telegram-монитор запущен")
                else:
                    logger.warning(
                        "Telegram-монитор: не удалось авторизоваться. "
                        "Запустите интерактивную авторизацию при первом использовании."
                    )
            except Exception as exc:
                logger.warning("Telegram-монитор не запущен: %s", exc)
        else:
            logger.info("Telegram-монитор отключён: не указаны API-данные")

        # -----------------------------------------------------------------
        # Мониторинг VK
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
            logger.info("VK-монитор инициализирован")
        else:
            logger.info("VK-монитор отключён: не указан access token")

        # -----------------------------------------------------------------
        # Мониторинг веб-сайтов
        # -----------------------------------------------------------------
        web_sources = cfg.get("sources", {}).get("websites", [])
        if web_sources:
            self.website_monitor = WebsiteMonitor(
                db=self.db,
                site_configs=web_sources,
                min_message_length=cfg.get("min_message_length", 20),
                request_timeout=cfg.get("request_timeout_seconds", 30),
                max_retries=cfg.get("max_retries", 3),
            )
            await self.website_monitor.load_initial_state()
            logger.info("Website-монитор инициализирован")
        else:
            logger.info("Website-монитор отключён: нет источников")

        # -----------------------------------------------------------------
        # Discord мониторинг (запускается как отдельная задача)
        # -----------------------------------------------------------------
        discord_token = cfg.get("discord_token", "")
        discord_sources = cfg.get("sources", {}).get("discord", [])
        if discord_token and discord_token != "YOUR_DISCORD_TOKEN_HERE" and discord_sources:
            self._discord_enabled = True
            logger.info("Discord-монитор будет запущен как фоновая задача")
        else:
            logger.info("Discord-монитор отключён: не указан токен")

        # -----------------------------------------------------------------
        # Планировщик
        # -----------------------------------------------------------------
        self.scheduler = Scheduler()

        check_interval = cfg.get("check_interval_minutes", 5)

        # Периодическая проверка Telegram-каналов
        if self._telegram_monitor_enabled:
            self.scheduler.add_interval_job(
                func=self._task_check_telegram,
                job_id="check_telegram",
                minutes=check_interval,
            )

        # Периодическая проверка VK-групп
        if self.vk_monitor:
            self.scheduler.add_interval_job(
                func=self._task_check_vk,
                job_id="check_vk",
                minutes=check_interval,
            )

        # Периодическая проверка веб-сайтов
        if self.website_monitor:
            web_interval = check_interval
            self.scheduler.add_interval_job(
                func=self._task_check_websites,
                job_id="check_websites",
                minutes=web_interval,
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

    async def _task_check_telegram(self) -> None:
        """Периодическая проверка Telegram-каналов."""
        if not self.tg_monitor or not self._telegram_monitor_enabled:
            return
        try:
            count = await self.tg_monitor.check_all_channels()
            if count > 0:
                logger.info("Telegram: обработано %d новых сообщений", count)
        except Exception as exc:
            logger.error("Ошибка проверки Telegram-каналов: %s", exc)

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

    async def _task_check_websites(self) -> None:
        """Периодическая проверка веб-сайтов."""
        if not self.website_monitor:
            return
        try:
            count = await self.website_monitor.check_all_sites()
            if count > 0:
                logger.info("Websites: обработано %d новых записей", count)
        except Exception as exc:
            logger.error("Ошибка проверки веб-сайтов: %s", exc)

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
                        await self.deduplicator.mark_as_duplicate(duplicate_of, msg_id)
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
                    )
                else:
                    # Если анализ не удался — сохраняем как low priority
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
        """Публикует одно сообщение."""
        msg_id = msg["id"]

        # Форматируем пост
        text = self.publisher.format_post(
            server_name=msg.get("server_name", "Unknown"),
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
        # Отделяем локальные пути (от Telegram-монитора) от URL
        local_images = [img for img in images if os.path.exists(img)]
        url_images = [img for img in images if img.startswith("http")]

        # Публикуем
        tg_msg_id = await self.publisher.publish_message(
            text=text,
            image_paths=local_images if local_images else None,
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
        """Очищает старые записи (старше 30 дней) из базы данных."""
        if not self.db:
            return

        try:
            # Удаляем обработанные сообщения старше 30 дней
            await self.db._connection.execute(
                """DELETE FROM messages
                   WHERE collected_at < datetime('now', '-30 days')
                     AND id IN (SELECT message_id FROM processed_messages)"""
            )
            # Удаляем необработанные сообщения старше 14 дней
            await self.db._connection.execute(
                """DELETE FROM messages
                   WHERE collected_at < datetime('now', '-14 days')
                     AND id NOT IN (SELECT message_id FROM processed_messages)"""
            )
            # Удаляем старые логи из БД
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

            discord_monitor = DiscordMonitor(
                db=self.db,
                token=self.config["discord_token"],
                server_configs=self.config.get("sources", {}).get("discord", []),
                min_message_length=self.config.get("min_message_length", 20),
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

        # Запускаем Discord-монитор в фоне
        if self._discord_enabled:
            asyncio.create_task(self._run_discord_monitor())

        # Настраиваем обработчики сигналов для graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._shutdown(s)),
                )
            except NotImplementedError:
                # Windows не поддерживает add_signal_handler
                pass

        logger.info("=" * 60)
        logger.info("DayZ News Monitor запущен и работает")
        logger.info("Нажмите Ctrl+C для остановки")
        logger.info("=" * 60)

        # Ожидаем сигнал завершения
        await self._shutdown_event.wait()

        await self._cleanup()

    async def _shutdown(self, signal_received) -> None:
        """Обрабатывает сигнал завершения."""
        sig_name = signal_received.name if hasattr(signal_received, "name") else str(signal_received)
        logger.info("Получен сигнал %s. Завершение работы...", sig_name)
        self._shutdown_event.set()

    async def _cleanup(self) -> None:
        """Освобождает ресурсы при завершении."""
        logger.info("Очистка ресурсов...")

        # Останавливаем планировщик
        if self.scheduler:
            await self.scheduler.stop()

        # Закрываем Publisher
        if self.publisher:
            await self.publisher.close()

        # Останавливаем Telegram-монитор
        if self.tg_monitor:
            await self.tg_monitor.stop()

        # Закрываем базу данных
        if self.db:
            await self.db.close()

        logger.info("DayZ News Monitor остановлен")


# =============================================================================
# Точка входа
# =============================================================================


def main():
    """Главная функция."""
    # Определяем путь к конфигу (по умолчанию рядом со скриптом)
    config_path = os.environ.get("DAYZ_CONFIG", "config.json")

    monitor = DayZNewsMonitor(config_path=config_path)

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
    except Exception as exc:
        logger.critical("Критическая ошибка: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
