"""
Веб-интерфейс DayZ News Monitor.
Flask-сервер с настройками, статусом и логами в реальном времени.
Запускается в фоне вместе с ботом.
"""

import json
import queue
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime
from logging import Handler, LogRecord, Formatter
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    Response,
    abort,
)


class LogStreamer(Handler):
    """Лог-хендлер, который захватывает записи и передаёт их в SSE."""

    def __init__(self, max_size=1000):
        super().__init__()
        self.logs: deque = deque(maxlen=max_size)
        self._listeners: list[queue.Queue] = []
        self.setFormatter(Formatter("%(message)s"))

    def emit(self, record: LogRecord) -> None:
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "level": record.levelname,
                "message": self.format(record),
            }
            self.logs.append(entry)
            dead = []
            for q in self._listeners:
                try:
                    q.put_nowait(entry)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._listeners.remove(q)
        except Exception:
            pass

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=500)
        self._listeners.append(q)
        # Сразу отправляем последние записи
        for entry in self.logs:
            try:
                q.put_nowait(entry)
            except Exception:
                break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        if q in self._listeners:
            self._listeners.remove(q)

    def get_recent(self, count: int = 200) -> list:
        return list(self.logs)[-count:]


class SharedState:
    """Общее состояние бота для отображения на дашборде."""

    def __init__(self):
        self.discord_connected = False
        self.discord_user = ""
        self.discord_guild = ""
        self.discord_channel = ""
        self.telegram_connected = False
        self.vk_connected = False
        self.ai_enabled = False
        self.db_connected = False
        self.messages_collected = 0
        self.messages_analyzed = 0
        self.messages_published = 0
        self.duplicates_found = 0
        self.last_activity = ""
        self.started_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        uptime = ""
        if self.started_at:
            try:
                started = datetime.fromisoformat(self.started_at)
                delta = datetime.now() - started
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                uptime = f"{hours}ч {minutes}м"
            except Exception:
                uptime = "N/A"
        return {
            "discord_connected": self.discord_connected,
            "discord_user": self.discord_user,
            "discord_guild": self.discord_guild,
            "discord_channel": self.discord_channel,
            "telegram_connected": self.telegram_connected,
            "vk_connected": self.vk_connected,
            "ai_enabled": self.ai_enabled,
            "db_connected": self.db_connected,
            "messages_collected": self.messages_collected,
            "messages_analyzed": self.messages_analyzed,
            "messages_published": self.messages_published,
            "duplicates_found": self.duplicates_found,
            "last_activity": self.last_activity,
            "uptime": uptime,
        }


class WebGUI:
    """Flask-веб-интерфейс для управления и мониторинга бота."""

    def __init__(
        self,
        config_path: str = "config.json",
        log_handler: LogStreamer = None,
        state: SharedState = None,
        port: int = 8080,
        auto_open: bool = True,
    ):
        self.config_path = config_path
        self.log_handler = log_handler or LogStreamer()
        self.state = state or SharedState()
        self.port = port
        self.auto_open = auto_open

        self.app = Flask(
            __name__,
            template_folder="templates",
            static_folder="static",
        )
        self._setup_routes()

    # -----------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------

    def _setup_routes(self):
        app = self.app

        @app.route("/")
        def index():
            return render_template("index.html")

        # --- Status ---
        @app.route("/api/status")
        def get_status():
            return jsonify(self.state.to_dict())

        # --- Config ---
        @app.route("/api/config")
        def get_config():
            try:
                cfg = self._load_config()
                return jsonify(self._mask_config(cfg))
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/config", methods=["PUT"])
        def save_config():
            try:
                data = request.get_json(force=True)
                cfg = self._load_config()

                # Обновляем только переданные поля (поддержка вложенных)
                for key, value in data.items():
                    if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                        cfg[key].update(value)
                    else:
                        cfg[key] = value

                self._save_config(cfg)
                return jsonify({"status": "ok", "message": "Конфигурация сохранена"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        # --- Logs ---
        @app.route("/api/logs")
        def get_logs():
            count = request.args.get("count", 200, type=int)
            level = request.args.get("level", "")
            logs = self.log_handler.get_recent(count)
            if level:
                logs = [l for l in logs if l["level"] == level.upper()]
            return jsonify(logs)

        @app.route("/api/logs/stream")
        def stream_logs():
            q = self.log_handler.subscribe()

            def generate():
                try:
                    while True:
                        try:
                            entry = q.get(timeout=30)
                            yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                        except queue.Empty:
                            yield f": keepalive\n\n"
                except GeneratorExit:
                    self.log_handler.unsubscribe(q)

            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

        # --- Restart hint ---
        @app.route("/api/restart", methods=["POST"])
        def restart():
            return jsonify({
                "status": "info",
                "message": "Перезапустите бота вручную (stop.bat → start.bat) для применения изменений.",
            })

    # -----------------------------------------------------------------
    # Config helpers
    # -----------------------------------------------------------------

    def _load_config(self) -> dict:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_config(self, cfg: dict) -> None:
        path = Path(self.config_path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _mask_config(cfg: dict) -> dict:
        """Маскирует секретные поля для отображения в GUI."""
        sensitive = [
            "discord_token",
            "telegram_bot_token",
            "openai_api_key",
            "vk_access_token",
        ]
        masked = dict(cfg)
        for key in sensitive:
            val = masked.get(key, "")
            if val and not str(val).startswith("YOUR_"):
                s = str(val)
                if len(s) > 8:
                    masked[key] = s[:4] + "••••" + s[-4:]
                else:
                    masked[key] = "••••"
        return masked

    # -----------------------------------------------------------------
    # Start / Stop
    # -----------------------------------------------------------------

    def run_in_thread(self) -> None:
        """Запускает веб-сервер в фоновом потоке."""
        t = threading.Thread(target=self._run_server, daemon=True, name="WebGUI")
        t.start()

        if self.auto_open:
            # Даём серверу секунду на старт, потом открываем браузер
            threading.Timer(1.5, self._open_browser).start()

    def _run_server(self) -> None:
        import werkzeug.serving

        werkzeug.serving._log = lambda *args, **kwargs: None
        self.app.run(
            host="127.0.0.1",
            port=self.port,
            debug=False,
            use_reloader=False,
        )

    def _open_browser(self) -> None:
        try:
            webbrowser.open(f"http://127.0.0.1:{self.port}")
        except Exception:
            pass
