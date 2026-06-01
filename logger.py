"""
Модуль логирования проекта DayZ News Monitor.
Настраивает ежедневную ротацию файлов логов (отдельный файл на каждый день).
Текущий день — logs/app.log, предыдущие дни — logs/app-YYYY-MM-DD.log
"""

import asyncio
import logging
import os
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler


def setup_logger(
    log_dir: str = "logs",
    log_level: int = logging.INFO,
    backup_count: int = 30,
) -> logging.Logger:
    """
    Создаёт и возвращает настроенный логгер проекта.
    Каждый день в полночь текущий лог переименовывается в app-YYYY-MM-DD.log,
    и начинается запись в новый app.log.
    Хранятся последние backup_count дней (по умолчанию 30).

    Args:
        log_dir: Директория для хранения файлов логов.
        log_level: Уровень логирования.
        backup_count: Количество хранимых дневных файлов логов.

    Returns:
        Настроенный экземпляр logging.Logger.
    """
    # Создаём директорию для логов, если она не существует
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("dayz_monitor")
    logger.setLevel(log_level)

    # Предотвращаем дублирование обработчиков при повторном вызове
    if logger.handlers:
        return logger

    # Форматирование логов
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Обработчик: файл (ротация каждый день в полночь) ---
    log_file = os.path.join(log_dir, "app.log")

    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )

    # Переименовываем rotated-файлы: app.log.2025-06-01 → app-2025-06-01.log
    def _namer(default_name: str) -> str:
        dir_name = os.path.dirname(default_name)
        base = os.path.basename(default_name)
        # default_name: "logs/app.log.2025-06-01"
        date_str = base.split(".")[-1]  # "2025-06-01"
        return os.path.join(dir_name, f"app-{date_str}.log")

    def _rotator(source: str, dest: str) -> None:
        if os.path.exists(source):
            os.rename(source, dest)

    file_handler.namer = _namer
    file_handler.rotator = _rotator

    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # --- Обработчик: консоль (stderr) ---
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("Логгер инициализирован. Файл логов: %s (хранение %d дней)", log_file, backup_count)
    return logger


class WebPanelHandler(logging.Handler):
    """
    Обработчик логов, отправляющий WARNING и ERROR записи на веб-панель.
    Использует fire-and-forget через asyncio.create_task().
    """

    def __init__(self, web_panel_url: str):
        super().__init__()
        self.web_panel_url = web_panel_url
        # Only forward WARNING and ERROR levels
        self.setLevel(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        if not self.web_panel_url:
            return

        try:
            from web_app_integration import send_log_to_panel
        except ImportError:
            return

        log_data = {
            "level": record.levelname.lower(),
            "module": record.name,
            "message": self.format(record),
            "details": "",
        }

        # Add traceback for errors if available
        if record.exc_info and record.exc_info[0] is not None:
            log_data["details"] = "".join(traceback.format_exception(*record.exc_info))

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_log_to_panel(log_data, self.web_panel_url))
        except RuntimeError:
            # No running loop — create a new one
            asyncio.create_task(send_log_to_panel(log_data, self.web_panel_url))


def add_web_panel_handler(web_panel_url: str):
    """
    Добавляет обработчик пересылки логов на веб-панель.
    Вызывать после загрузки конфига, когда web_panel_url известен.
    """
    if not web_panel_url:
        return
    handler = WebPanelHandler(web_panel_url)
    # Simple formatter for the web panel
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info("Веб-панель: пересылка логов (%s) включена", web_panel_url)


# Глобальный экземпляр логгера
logger = setup_logger()
