"""
Десктопный GUI для DayZ News Monitor.
Создаёт отдельное окно с тёмной темой, статусом, логами и настройками.
Работает в отдельном потоке, не блокируя основной бот.
"""

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from logging import Handler, LogRecord, Formatter
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk

from logger import logger


# =====================================================================
# Лог-хендлер для захвата записей
# =====================================================================

class LogCapture(Handler):
    """Лог-хендлер, который передаёт записи в GUI."""

    def __init__(self, max_size=500):
        super().__init__()
        self.entries: list[dict] = []
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self.setFormatter(Formatter("%(message)s"))

    def emit(self, record: LogRecord) -> None:
        try:
            entry = {
                "time": datetime.fromtimestamp(record.created).strftime(
                    "%H:%M:%S"
                ),
                "level": record.levelname,
                "message": self.format(record),
            }
            self.entries.append(entry)
            if len(self.entries) > 2000:
                self.entries = self.entries[-1000:]
            try:
                self._queue.put_nowait(entry)
            except queue.Full:
                pass
        except Exception:
            pass

    def get_entry(self, timeout=0.05):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


# =====================================================================
# Основное окно
# =====================================================================

class DesktopGUI:
    """Десктопное окно мониторинга DayZ News Monitor."""

    # Цвета
    BG = "#1a1a2e"
    BG2 = "#16213e"
    BG3 = "#0f3460"
    CARD = "#1e2a4a"
    CARD_BORDER = "#2a3a5e"
    ACCENT = "#58a6ff"
    GREEN = "#3fb950"
    RED = "#f85149"
    YELLOW = "#d29922"
    TEXT = "#e6edf3"
    TEXT2 = "#8b949e"
    TEXT3 = "#6e7681"
    INPUT_BG = "#0d1117"
    INPUT_BORDER = "#30363d"

    def __init__(
        self,
        config_path: str = "config.json",
        log_capture: LogCapture = None,
    ):
        self.config_path = config_path
        self.log_capture = log_capture or LogCapture()
        self._running = True
        self._status = {
            "discord": False,
            "telegram": False,
            "ai": False,
            "db": False,
            "vk": False,
            "discord_user": "",
            "discord_guild": "",
            "discord_channel": "",
            "messages": 0,
            "analyzed": 0,
            "published": 0,
            "duplicates": 0,
        }
        self._log_level_filter = "ALL"
        self._started_at = datetime.now()

    # -----------------------------------------------------------------
    # Запуск в отдельном потоке
    # -----------------------------------------------------------------

    def run_in_thread(self) -> None:
        t = threading.Thread(target=self._run, daemon=True, name="DesktopGUI")
        t.start()

    def _run(self) -> None:
        try:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except Exception:
            pass

        self.root = ctk.CTk()
        self.root.title("DayZ News Monitor")
        self.root.geometry("900x650")
        self.root.minsize(750, 500)
        self.root.configure(fg_color=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.root.after(500, self._poll_logs)

        self.root.mainloop()
        self._running = False

    def _on_close(self) -> None:
        self._running = False
        try:
            self.root.destroy()
        except Exception:
            pass

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------

    def _build_ui(self):
        # --- Header ---
        header = ctk.CTkFrame(self.root, fg_color=self.BG2, height=50)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="\U0001f3ae DayZ News Monitor",
            font=("Segoe UI", 16, "bold"),
            text_color=self.ACCENT,
        ).pack(side="left", padx=16)

        self.status_label = ctk.CTkLabel(
            header, text="\u25cf Остановлен",
            font=("Segoe UI", 13),
            text_color=self.RED,
        )
        self.status_label.pack(side="right", padx=16)

        self.uptime_label = ctk.CTkLabel(
            header, text="00:00:00",
            font=("Consolas", 12),
            text_color=self.TEXT2,
        )
        self.uptime_label.pack(side="right", padx=8)

        ctk.CTkLabel(
            header, text="Аптайм:",
            font=("Segoe UI", 12),
            text_color=self.TEXT3,
        ).pack(side="right", padx=(0, 4))

        # --- Notebook (tabs) ---
        self.notebook = ctk.CTkTabview(self.root, fg_color=self.BG)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        tab_dashboard = self.notebook.add("\U0001f4ca Дашборд")
        tab_settings = self.notebook.add("\u2699\ufe0f Настройки")
        tab_logs = self.notebook.add("\U0001f4cb Логи")

        self._build_dashboard(tab_dashboard)
        self._build_settings(tab_settings)
        self._build_logs(tab_logs)

    # === DASHBOARD ===

    def _build_dashboard(self, parent):
        # Статусы компонентов
        status_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        status_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._status_cards = {}

        for i, (key, label, icon) in enumerate([
            ("discord", "Discord", "\U0001f6e4\ufe0f"),
            ("telegram", "Telegram", "\U0001f4e8"),
            ("ai", "AI Анализатор", "\U0001f9e0"),
            ("db", "База данных", "\U0001f5c4\ufe0f"),
            ("vk", "VK", "\U0001f5fa\ufe0f"),
        ]):
            card = ctk.CTkFrame(status_frame, fg_color=self.BG2, width=160)
            card.pack(side="left", padx=4, pady=6, fill="y", expand=True)
            card.pack_propagate(False)

            ctk.CTkLabel(
                card, text=f"{icon} {label}",
                font=("Segoe UI", 11),
                text_color=self.TEXT2,
            ).pack(pady=(8, 0))

            val_label = ctk.CTkLabel(
                card, text="\u25cf Отключён",
                font=("Segoe UI", 12, "bold"),
                text_color=self.TEXT3,
            )
            val_label.pack(pady=(2, 2))

            info_label = ctk.CTkLabel(
                card, text="",
                font=("Segoe UI", 10),
                text_color=self.TEXT3,
                wraplength=140,
            )
            info_label.pack(pady=(0, 8))

            self._status_cards[key] = {
                "value": val_label,
                "info": info_label,
            }

        # Счётчики
        counter_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        counter_frame.pack(fill="x", padx=8, pady=4)

        self._counter_labels = {}
        counters = [
            ("messages", "Сообщений собрано", "\U0001f4dd"),
            ("analyzed", "Проанализировано", "\U0001f50d"),
            ("published", "Опубликовано", "\U0001f4e3"),
            ("duplicates", "Дубликатов", "\U0001f4ca"),
        ]

        for key, label, icon in counters:
            card = ctk.CTkFrame(counter_frame, fg_color=self.BG2)
            card.pack(side="left", padx=4, pady=6, fill="both", expand=True)

            ctk.CTkLabel(
                card, text=f"{icon} {label}",
                font=("Segoe UI", 10),
                text_color=self.TEXT2,
            ).pack(pady=(8, 0))

            num_label = ctk.CTkLabel(
                card, text="0",
                font=("Segoe UI", 24, "bold"),
                text_color=self.TEXT,
            )
            num_label.pack(pady=(0, 8))
            self._counter_labels[key] = num_label

        # Discord info
        info_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        info_frame.pack(fill="x", padx=8, pady=4)

        self._discord_detail = ctk.CTkLabel(
            info_frame,
            text="Discord: ожидание подключения...",
            font=("Segoe UI", 11),
            text_color=self.TEXT2,
            anchor="w",
        )
        self._discord_detail.pack(fill="x", padx=12, pady=10)

    # === SETTINGS ===

    def _build_settings(self, parent):
        # Скроллбар
        canvas = ctk.CTkScrollableFrame(parent, fg_color=self.BG)
        canvas.pack(fill="both", expand=True, padx=8, pady=8)

        self._settings_entries = {}

        sections = [
            ("\U0001f6e4\ufe0f Discord", [
                ("discord_token", "Discord Token", "text", "Токен вашего аккаунта Discord"),
                ("sources_discord_guild_id", "Guild ID", "text", "ID сервера"),
                ("sources_discord_channel_id", "Channel ID", "text", "ID канала"),
            ]),
            ("\U0001f4e8 Telegram", [
                ("telegram_bot_token", "Bot Token", "text", "Токен от @BotFather"),
                ("telegram_channel_id", "Channel ID", "text", "-100xxxxxxxxxx"),
            ]),
            ("\U0001f9e0 AI / NVIDIA API", [
                ("openai_api_key", "API Key", "text", "nvapi-..."),
                ("openai_base_url", "Base URL", "text", "https://integrate.api.nvidia.com/v1"),
                ("openai_model", "Модель", "text", "meta/llama-3.1-8b-instruct"),
            ]),
            ("\u23f0 Расписание", [
                ("check_interval_minutes", "Интервал проверки (мин)", "number", "5"),
                ("daily_summary_hour", "Час сводки (UTC)", "number", "10"),
                ("min_message_length", "Мин. длина сообщения", "number", "20"),
                ("similarity_threshold", "Порог похожести", "number", "0.85"),
            ]),
            ("\U0001f5fa\ufe0f VK (опционально)", [
                ("vk_access_token", "VK Access Token", "text", "Пусто = выключено"),
            ]),
        ]

        for section_title, fields in sections:
            frame = ctk.CTkFrame(canvas, fg_color=self.CARD)
            frame.pack(fill="x", pady=(6, 3))

            ctk.CTkLabel(
                frame, text=section_title,
                font=("Segoe UI", 13, "bold"),
                text_color=self.ACCENT,
            ).pack(anchor="w", padx=12, pady=(10, 4))

            for key, label, input_type, hint in fields:
                row = ctk.CTkFrame(frame, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=2)

                ctk.CTkLabel(
                    row, text=label + ":",
                    font=("Segoe UI", 11),
                    text_color=self.TEXT2,
                    width=200,
                    anchor="w",
                ).pack(side="left")

                entry = ctk.CTkEntry(
                    row,
                    fg_color=self.INPUT_BG,
                    border_color=self.INPUT_BORDER,
                    border_width=1,
                    text_color=self.TEXT,
                    font=("Consolas", 12),
                    width=350,
                    show="*" if "token" in key or "key" in key else "",
                )
                entry.pack(side="left", padx=(0, 8), fill="x", expand=True)
                self._settings_entries[key] = entry

                ctk.CTkLabel(
                    row, text=hint,
                    font=("Segoe UI", 10),
                    text_color=self.TEXT3,
                    width=200,
                    anchor="w",
                ).pack(side="left")

            # Тогглы для публикации
            if section_title == "\u23f0 Расписание":
                toggle_frame = ctk.CTkFrame(frame, fg_color="transparent")
                toggle_frame.pack(fill="x", padx=12, pady=(8, 10))

                self._toggle_vars = {}
                for key, label in [
                    ("publish_high_priority", "Публиковать High"),
                    ("publish_medium_priority", "Публиковать Medium"),
                    ("publish_low_priority", "Публиковать Low"),
                ]:
                    var = tk.BooleanVar()
                    cb = ctk.CTkCheckBox(
                        toggle_frame,
                        text=label,
                        variable=var,
                        font=("Segoe UI", 11),
                        text_color=self.TEXT2,
                        fg_color=self.INPUT_BORDER,
                        hover_color=self.ACCENT,
                    )
                    cb.pack(side="left", padx=(0, 20))
                    self._toggle_vars[key] = var

        # Кнопки
        btn_frame = ctk.CTkFrame(canvas, fg_color="transparent")
        btn_frame.pack(fill="x", pady=12)

        save_btn = ctk.CTkButton(
            btn_frame, text="\U0001f4be Сохранить настройки",
            font=("Segoe UI", 12, "bold"),
            fg_color=self.ACCENT,
            hover_color="#79b8ff",
            width=200, height=38,
            command=self._save_config,
        )
        save_btn.pack(side="left", padx=4)

        reload_btn = ctk.CTkButton(
            btn_frame, text="\U0001f504 Перезагрузить",
            font=("Segoe UI", 12, "bold"),
            fg_color="#2a3a5e",
            hover_color="#3a4a6e",
            width=200, height=38,
            command=self._load_config,
        )
        reload_btn.pack(side="left", padx=4)

    # === LOGS ===

    def _build_logs(self, parent):
        # Панель фильтров
        filter_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        filter_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._filter_buttons = {}
        for level in ("ALL", "INFO", "WARNING", "ERROR", "DEBUG"):
            btn = ctk.CTkButton(
                filter_frame, text=level,
                font=("Segoe UI", 11, "bold"),
                width=70, height=30,
                fg_color=self.ACCENT if level == "ALL" else self.BG3,
                hover_color="#79b8ff",
                command=lambda l=level: self._set_filter(l),
            )
            btn.pack(side="left", padx=3, pady=6)
            self._filter_buttons[level] = btn

        self._log_count_label = ctk.CTkLabel(
            filter_frame, text="0 записей",
            font=("Segoe UI", 10),
            text_color=self.TEXT3,
        )
        self._log_count_label.pack(side="right", padx=12)

        clear_btn = ctk.CTkButton(
            filter_frame, text="\U0001f5d1 Очистить",
            font=("Segoe UI", 10),
            width=80, height=30,
            fg_color=self.BG3,
            hover_color=self.RED,
            command=self._clear_logs,
        )
        clear_btn.pack(side="right", padx=3, pady=6)

        # Текст логов
        self._log_text = tk.Text(
            parent,
            bg=self.INPUT_BG,
            fg=self.TEXT,
            font=("Consolas", 11),
            insertbackground=self.TEXT,
            selectbackground=self.BG3,
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            state="disabled",
            cursor="arrow",
        )
        self._log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Цвета для уровней
        self._log_text.tag_configure("TIME", foreground=self.TEXT3)
        self._log_text.tag_configure("LEVEL_INFO", foreground=self.ACCENT)
        self._log_text.tag_configure("LEVEL_WARNING", foreground=self.YELLOW)
        self._log_text.tag_configure("LEVEL_ERROR", foreground=self.RED)
        self._log_text.tag_configure("LEVEL_DEBUG", foreground=self.TEXT3)
        self._log_text.tag_configure("MSG", foreground=self.TEXT)

        self._total_log_lines = 0

    # -----------------------------------------------------------------
    # Логика
    # -----------------------------------------------------------------

    def _set_filter(self, level: str) -> None:
        self._log_level_filter = level
        for l, btn in self._filter_buttons.items():
            btn.configure(
                fg_color=self.ACCENT if l == level else self.BG3,
            )

    def _clear_logs(self) -> None:
        self._total_log_lines = 0
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        self._log_count_label.configure(text="0 записей")

    def _add_log_line(self, entry: dict) -> None:
        level = entry["level"]
        if self._log_level_filter != "ALL" and level != self._log_level_filter:
            return

        time_str = entry["time"]
        msg = entry["message"]

        self._log_text.configure(state="normal")
        self._log_text.insert("end", f" {time_str} ", "TIME")
        self._log_text.insert("end", f"{level:>8} ", f"LEVEL_{level}")
        self._log_text.insert("end", f"{msg}\n", "MSG")
        self._total_log_lines += 1

        # Ограничиваем строки
        if self._total_log_lines > 2000:
            self._log_text.delete("1.0", "500 lines")
            self._total_log_lines -= 500

        self._log_text.see("end")
        self._log_text.configure(state="disabled")
        self._log_count_label.configure(text=f"{self._total_log_lines} записей")

    def _poll_logs(self) -> None:
        """Вызывается через root.after() — читает логи и обновляет uptime."""
        if not self._running:
            return

        # Считываем все накопившиеся записи
        while True:
            entry = self.log_capture.get_entry(timeout=0.01)
            if not entry:
                break
            try:
                self._add_log_line(entry)
            except Exception:
                pass

        # Обновляем аптайм
        try:
            delta = datetime.now() - self._started_at
            h, rem = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            self.uptime_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        except Exception:
            pass

        # Планируем следующий вызов через 300мс
        try:
            self.root.after(300, self._poll_logs)
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Config
    # -----------------------------------------------------------------

    def _load_config(self) -> None:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return

        # Простые поля
        simple = [
            "discord_token", "telegram_bot_token", "telegram_channel_id",
            "openai_api_key", "openai_base_url", "openai_model",
            "vk_access_token", "check_interval_minutes",
            "daily_summary_hour", "min_message_length",
            "similarity_threshold",
        ]
        for key in simple:
            el = self._settings_entries.get(key)
            if el and key in cfg:
                el.delete(0, "end")
                el.insert(0, str(cfg[key]))

        # Вложенные: sources.discord
        sources = cfg.get("sources", {})
        discord = sources.get("discord", {})
        for key in ("sources_discord_guild_id", "sources_discord_channel_id"):
            el = self._settings_entries.get(key)
            if el:
                el.delete(0, "end")
                cfg_key = key.replace("sources_discord_", "")
                el.insert(0, str(discord.get(cfg_key, "")))

        # Тогглы
        for key, var in self._toggle_vars.items():
            var.set(cfg.get(key, False))

    def _save_config(self) -> None:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        # Простые поля
        simple = [
            "discord_token", "telegram_bot_token", "telegram_channel_id",
            "openai_api_key", "openai_base_url", "openai_model",
            "vk_access_token", "check_interval_minutes",
            "daily_summary_hour", "min_message_length",
            "similarity_threshold",
        ]
        for key in simple:
            el = self._settings_entries.get(key)
            if el:
                val = el.get()
                if key in ("check_interval_minutes", "daily_summary_hour",
                           "min_message_length"):
                    try:
                        val = int(val)
                    except ValueError:
                        pass
                elif key == "similarity_threshold":
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                cfg[key] = val

        # Вложенные: sources.discord
        if "sources" not in cfg:
            cfg["sources"] = {}
        if "discord" not in cfg["sources"]:
            cfg["sources"]["discord"] = {}

        cfg["sources"]["discord"]["guild_id"] = (
            self._settings_entries["sources_discord_guild_id"].get()
        )
        cfg["sources"]["discord"]["channel_id"] = (
            self._settings_entries["sources_discord_channel_id"].get()
        )

        # Тогглы
        for key, var in self._toggle_vars.items():
            cfg[key] = var.get()

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            logger.info("Настройки сохранены через GUI (перезапустите бота)")
        except Exception as e:
            logger.error("Ошибка сохранения настроек: %s", e)

    # -----------------------------------------------------------------
    # Public API — вызывается из bot.py для обновления статуса
    # -----------------------------------------------------------------

    def update_status(self, key: str, value) -> None:
        """Обновляет статус компонента на дашборде."""
        self._status[key] = value
        try:
            self.root.after_idle(self._refresh_status)
        except Exception:
            pass

    def increment_counter(self, key: str) -> None:
        """Увеличивает счётчик на 1."""
        self._status[key] = self._status.get(key, 0) + 1
        try:
            self.root.after_idle(self._refresh_counters)
        except Exception:
            pass

    def _refresh_status(self) -> None:
        s = self._status

        # Статусы компонентов
        components = {
            "discord": (s["discord"], s["discord_user"] or "",
                       f"{s['discord_guild']} / #{s['discord_channel']}" if s["discord_guild"] else ""),
            "telegram": (s["telegram"], "\u2714 Подключён" if s["telegram"] else "", ""),
            "ai": (s["ai"], "\u2714 Активен" if s["ai"] else "", ""),
            "db": (s["db"], "\u2714 Подключена" if s["db"] else "", ""),
            "vk": (s["vk"], "\u2714 Активен" if s["vk"] else "", ""),
        }

        for key, (connected, value_text, info_text) in components.items():
            card = self._status_cards.get(key)
            if not card:
                continue
            if connected:
                card["value"].configure(text=f"\u25cf {value_text}", text_color=self.GREEN)
            else:
                card["value"].configure(text="\u25cf Отключён", text_color=self.TEXT3)
            card["info"].configure(text=info_text)

        # Глобальный статус
        if s["discord"] or s["db"]:
            self.status_label.configure(text="\u25cf Работает", text_color=self.GREEN)
        else:
            self.status_label.configure(text="\u25cf Остановлен", text_color=self.RED)

        # Discord деталь
        if s["discord"]:
            self._discord_detail.configure(
                text=f"Discord: {s['discord_user']} — "
                     f"{s['discord_guild']} / #{s['discord_channel']}",
            )
        else:
            self._discord_detail.configure(text="Discord: ожидание подключения...")

    def _refresh_counters(self) -> None:
        for key, label in self._counter_labels.items():
            val = self._status.get(key, 0)
            label.configure(text=str(val))
