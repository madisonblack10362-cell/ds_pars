"""
Общий трекер статистики мониторов.

Все мониторы обновляют статистику здесь. GUI читает отсюда.
Потокобезопасный через threading.Lock.

Использование в мониторах:
    from monitor_stats import stats
    stats.record_check("workshop", found=15, processed=8, published=5)
    stats.increment("workshop", "errors")
"""

import threading
import time
from datetime import datetime


class MonitorStats:
    """Синглтон для сбора статистики всех мониторов."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._monitors = {}
                    cls._instance._data_lock = threading.Lock()
        return cls._instance

    def ensure_monitor(self, name: str, display_name: str = "", icon: str = ""):
        """Убедиться, что монитор зарегистрирован."""
        with self._data_lock:
            if name not in self._monitors:
                self._monitors[name] = {
                    "display_name": display_name or name,
                    "icon": icon,
                    "checks": 0,
                    "found": 0,
                    "processed": 0,
                    "published": 0,
                    "errors": 0,
                    "skipped": 0,
                    "last_check": None,
                    "last_activity": None,
                    "status": "idle",
                    "detail": "",
                    "started_at": time.time(),
                    "history": [],
                }

    def record_check(self, name: str, found: int = 0, processed: int = 0,
                     published: int = 0, errors: int = 0, skipped: int = 0):
        """Записать результаты одной проверки (check cycle)."""
        with self._data_lock:
            self.ensure_monitor(name)
            d = self._monitors[name]
            d["checks"] += 1
            d["found"] += found
            d["processed"] += processed
            d["published"] += published
            d["errors"] += errors
            d["skipped"] += skipped
            d["last_check"] = datetime.now().isoformat()
            d["last_activity"] = datetime.now().isoformat()
            d["history"].append({
                "time": time.time(),
                "found": found,
                "processed": processed,
                "published": published,
                "errors": errors,
            })
            if len(d["history"]) > 60:
                d["history"] = d["history"][-60:]

    def increment(self, name: str, field: str, count: int = 1):
        """Увеличить конкретное поле на count."""
        with self._data_lock:
            self.ensure_monitor(name)
            if field in self._monitors[name]:
                self._monitors[name][field] += count
            self._monitors[name]["last_activity"] = datetime.now().isoformat()

    def set_status(self, name: str, status: str, detail: str = ""):
        """Установить статус монитора (active/idle/error/checking)."""
        with self._data_lock:
            self.ensure_monitor(name)
            self._monitors[name]["status"] = status
            self._monitors[name]["detail"] = detail
            self._monitors[name]["last_activity"] = datetime.now().isoformat()

    def get(self, name: str) -> dict:
        """Получить статистику одного монитора (копия)."""
        with self._data_lock:
            return dict(self._monitors.get(name, {}))

    def get_all(self) -> dict:
        """Получить статистику всех мониторов (копия)."""
        with self._data_lock:
            return {k: dict(v) for k, v in self._monitors.items()}

    def get_history(self, name: str) -> list:
        """Получить историю проверок монитора."""
        with self._data_lock:
            if name in self._monitors:
                return list(self._monitors[name]["history"])
            return []


# Глобальный экземпляр
stats = MonitorStats()