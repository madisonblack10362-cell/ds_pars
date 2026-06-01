"""
Модуль логирования проекта DayZ News Monitor.
Настраивает ежедневную ротацию файлов логов (отдельный файл на каждый день).
Текущий день — logs/app.log, предыдущие дни — logs/app-YYYY-MM-DD.log
"""

import logging
import os
import sys
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


# Глобальный экземпляр логгера
logger = setup_logger()
