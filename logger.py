"""
Модуль логирования проекта DayZ News Monitor.
Создаёт отдельный файл логов на каждый запуск с датой и временем в имени.
Файлы: logs/2025-06-02_14-30-00.log

Консоль — цветной с иконками, файл — простой текст.
"""

import asyncio
import logging
import os
import sys
import traceback
from datetime import datetime

# ─── ANSI цвета ──────────────────────────────────────────────────────────
class _C:
    """ANSI escape-коды."""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    # Уровни
    DEBUG   = "\033[36m"   # cyan
    INFO    = "\033[37m"   # white
    WARNING = "\033[33m"   # yellow
    ERROR   = "\033[31m"   # red
    CRITICAL= "\033[35;1m" # magenta bold
    # Акцент
    BLUE   = "\033[34m"   # blue
    GREEN  = "\033[32m"   # green
    GRAY   = "\033[90m"    # gray
    BG     = "\033[48;5;236m"  # dark bg for headers


class ColoredFormatter(logging.Formatter):
    """
    Цветной форматтер для консоли.
    
    Примеры вывода:
      12:00:00  INFO  │ Конфигурация загружена (12 ключей)
      12:00:00  ⚠️ WARN │ Discord-монитор отключён
      12:00:00  ❌ ERR  │ Ошибка отправки: timeout
    """

    # Иконки для уровней
    LEVEL_ICONS = {
        logging.DEBUG:    "🐛",
        logging.INFO:     "ℹ️ ",
        logging.WARNING:  "⚠️ ",
        logging.ERROR:    "❌ ",
        logging.CRITICAL: "🔥",
    }

    LEVEL_COLORS = {
        logging.DEBUG:    _C.DEBUG,
        logging.INFO:     _C.INFO,
        logging.WARNING:  _C.WARNING,
        logging.ERROR:    _C.ERROR,
        logging.CRITICAL: _C.CRITICAL,
    }

    LEVEL_TAGS = {
        logging.DEBUG:    "DBG",
        logging.INFO:     "INF",
        logging.WARNING:  "WRN",
        logging.ERROR:    "ERR",
        logging.CRITICAL: "CRT",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Цвет уровня
        color = self.LEVEL_COLORS.get(record.levelno, _C.INFO)
        tag   = self.LEVEL_TAGS.get(record.levelno, "???")
        icon  = self.LEVEL_ICONS.get(record.levelno, "  ")

        # Время
        time_str = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # Модуль (если не dayz_monitor — показываем)
        module = ""
        if record.name != "dayz_monitor":
            module = f"{_C.DIM}{record.name}{_C.RESET} │ "

        # Сообщение
        msg = record.getMessage()

        # Если есть аргументы, форматируем
        if record.args:
            try:
                msg = msg % record.args
            except (TypeError, ValueError):
                msg = str(record.args[0]) if record.args else msg

        # Формируем строку
        line = (
            f"{_C.DIM}{time_str}{_C.RESET}  "
            f"{icon}{_C.BOLD}{color}{tag}{_C.RESET}  "
            f"│ {module}"
            f"{_C.RESET}{msg}"
        )

        # Exception info
        if record.exc_info and record.exc_info[0] is not None:
            line += "\n" + self.formatException(record.exc_info)

        return line


class _FileFormatter(logging.Formatter):
    """Простой форматтер для файла логов — без цветов, с датой."""

    def format(self, record: logging.LogRecord) -> str:
        time_str = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        module = record.name if record.name != "dayz_monitor" else ""
        prefix = f"{time_str} | {record.levelname:8s}"
        if module:
            prefix += f" | {module}"
        msg = record.getMessage()
        if record.args:
            try:
                msg = msg % record.args
            except (TypeError, ValueError):
                msg = str(record.args[0]) if record.args else msg
        line = f"{prefix} | {msg}"
        if record.exc_info and record.exc_info[0] is not None:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logger(
    log_dir: str = "logs",
    log_level: int = logging.INFO,
) -> logging.Logger:
    """
    Создаёт и возвращает настроенный логгер проекта.
    Каждый запуск создаёт новый файл логов с датой и временем:
      logs/2025-06-02_14-30-00.log

    Консоль — цветной с иконками.
    Файл   — простой текст с датой.

    Args:
        log_dir: Директория для хранения файлов логов.
        log_level: Уровень логирования.

    Returns:
        Настроенный экземпляр logging.Logger.
    """
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("dayz_monitor")
    logger.setLevel(log_level)

    # Предотвращаем дублирование обработчиков
    if logger.handlers:
        return logger

    # --- Файл логов ---
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"{now}.log")

    file_handler = logging.FileHandler(filename=log_file, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(_FileFormatter())
    logger.addHandler(file_handler)

    # --- Консоль (цветной) ---
    console_handler = logging.StreamHandler(stream=sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    logger.info("Логгер инициализирован. Файл логов: %s", log_file)
    return logger


class WebPanelHandler(logging.Handler):
    """
    Обработчик логов, отправляющий WARNING и ERROR записи на веб-панель.
    Использует fire-and-forget через asyncio.create_task().
    """

    def __init__(self, web_panel_url: str):
        super().__init__()
        self.web_panel_url = web_panel_url
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

        if record.exc_info and record.exc_info[0] is not None:
            log_data["details"] = "".join(traceback.format_exception(*record.exc_info))

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_log_to_panel(log_data, self.web_panel_url))
        except RuntimeError:
            # Нет event loop (вызов из thread pool) — пропускаем отправку на веб-панель
            pass


def add_web_panel_handler(web_panel_url: str):
    """
    Добавляет обработчик пересылки логов на веб-панель.
    Вызывать после загрузки конфига, когда web_panel_url известен.
    """
    if not web_panel_url:
        return
    handler = WebPanelHandler(web_panel_url)
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info("Веб-панель: пересылка логов (%s) включена", web_panel_url)


# Глобальный экземпляр логгера
logger = setup_logger()
