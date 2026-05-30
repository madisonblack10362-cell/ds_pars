"""
Модуль логирования проекта DayZ News Monitor.
Настраивает_rotating файловый и консольный обработчики логов.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(
    log_file: str = "logs/app.log",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Создаёт и возвращает настроенный логгер проекта.

    Args:
        log_file: Путь к файлу логов.
        log_level: Уровень логирования.
        max_bytes: Максимальный размер файла лога в байтах (по умолчанию 10 МБ).
        backup_count: Количество хранимых резервных копий.

    Returns:
        Настроенный экземпляр logging.Logger.
    """
    # Создаём директорию для логов, если она не существует
    log_dir = os.path.dirname(log_file)
    if log_dir:
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

    # --- Обработчик: файл (с ротацией) ---
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # --- Обработчик: консоль (stderr) ---
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.info("Логгер инициализирован. Файл логов: %s", log_file)
    return logger


# Глобальный экземпляр логгера
logger = setup_logger()
