"""
Модуль планировщика задач проекта DayZ News Monitor.
Настраивает APScheduler для периодического запуска задач мониторинга,
анализа и публикации.

Используется BackgroundScheduler (работает в отдельном потоке),
а не AsyncIOScheduler, который блокирует asyncio event loop на Windows.
Асинхронные задачи-корутины автоматически пробрасываются в event loop
через asyncio.run_coroutine_threadsafe().
"""

import asyncio
import functools
import inspect
from datetime import datetime
from typing import Callable, Awaitable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from logger import logger


class Scheduler:
    """
    Планировщик периодических задач.
    Управляет расписанием мониторинга, анализа и публикации новостей.

    Использует BackgroundScheduler — работает в собственном потоке,
    не блокирует asyncio event loop (критично для Windows).
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._jobs: dict[str, str] = {}

    async def start(self) -> None:
        """Запускает планировщик."""
        if self._running:
            logger.warning("Планировщик уже запущен")
            return

        # Сохраняем ссылку на текущий event loop для проброса корутин
        self._loop = asyncio.get_running_loop()
        self._scheduler.start()
        self._running = True
        logger.info(
            "Планировщик запущен (BackgroundScheduler). Зарегистрировано задач: %d",
            len(self._scheduler.get_jobs()),
        )

    async def stop(self) -> None:
        """Останавливает планировщик."""
        if not self._running:
            return

        self._scheduler.shutdown(wait=True)
        self._running = False
        self._loop = None
        logger.info("Планировщик остановлен")

    def _run_async_job(self, coro_func: Callable, **kwargs) -> None:
        """Пробрасывает асинхронную функцию из потока планировщика в event loop."""
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro_func(**kwargs), self._loop)
            future.add_done_callback(self._on_job_done)
        else:
            logger.warning("Планировщик: event loop недоступен для задачи")

    @staticmethod
    def _on_job_done(future: asyncio.Future) -> None:
        """Логирует ошибки из задач планировщика."""
        try:
            future.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Планировщик: ошибка в задаче: %s", exc, exc_info=True)

    def add_interval_job(
        self,
        func: Callable,
        job_id: str,
        minutes: int = 5,
        seconds: int = 0,
        start_date: Optional[datetime] = None,
        replace_existing: bool = True,
        **kwargs,
    ) -> None:
        """
        Добавляет задачу с интервалом повторения.

        Args:
            func: Функция для выполнения (может быть async — будет проброшена в event loop).
            job_id: Уникальный идентификатор задачи.
            minutes: Интервал в минутах.
            seconds: Дополнительный интервал в секундах.
            start_date: Дата/время первого запуска.
            replace_existing: Заменять существующую задачу с таким ID.
            **kwargs: Дополнительные аргументы, передаваемые в func.
        """
        # Если функция асинхронная — оборачиваем для проброса в event loop
        if inspect.iscoroutinefunction(func):
            actual_func = functools.partial(self._run_async_job, func)
        else:
            actual_func = func

        trigger = IntervalTrigger(
            minutes=minutes,
            seconds=seconds,
            start_date=start_date,
        )

        self._scheduler.add_job(
            actual_func,
            trigger=trigger,
            id=job_id,
            replace_existing=replace_existing,
            kwargs=kwargs,
            misfire_grace_time=120,
            coalesce=True,
        )
        self._jobs[job_id] = f"interval({minutes}m {seconds}s)"
        logger.info(
            "Задача '%s' добавлена: каждые %d мин %d сек",
            job_id,
            minutes,
            seconds,
        )

    def add_cron_job(
        self,
        func: Callable,
        job_id: str,
        hour: int = 10,
        minute: int = 0,
        day_of_week: str = "*",
        replace_existing: bool = True,
        **kwargs,
    ) -> None:
        """
        Добавляет задачу по расписанию (cron).

        Args:
            func: Функция для выполнения (может быть async — будет проброшена в event loop).
            job_id: Уникальный идентификатор задачи.
            hour: Час запуска (UTC).
            minute: Минута запуска.
            day_of_week: День недели ('mon-fri', '*', 'mon', и т.д.).
            replace_existing: Заменять существующую задачу.
            **kwargs: Аргументы для func.
        """
        # Если функция асинхронная — оборачиваем для проброса в event loop
        if inspect.iscoroutinefunction(func):
            actual_func = functools.partial(self._run_async_job, func)
        else:
            actual_func = func

        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            day_of_week=day_of_week,
        )

        self._scheduler.add_job(
            actual_func,
            trigger=trigger,
            id=job_id,
            replace_existing=replace_existing,
            kwargs=kwargs,
            misfire_grace_time=300,
            coalesce=True,
        )
        self._jobs[job_id] = f"cron({hour:02d}:{minute:02d} {day_of_week})"
        logger.info(
            "Задача '%s' добавлена: каждый день в %02d:%02d UTC",
            job_id,
            hour,
            minute,
        )

    def remove_job(self, job_id: str) -> bool:
        """Удаляет задачу по идентификатору."""
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            logger.info("Задача '%s' удалена", job_id)
            return True
        except Exception:
            logger.warning("Не удалось удалить задачу '%s'", job_id)
            return False

    def get_jobs_info(self) -> dict[str, str]:
        """Возвращает словарь с информацией о зарегистрированных задачах."""
        return dict(self._jobs)

    @property
    def running(self) -> bool:
        """Возвращает True, если планировщик активен."""
        return self._running
