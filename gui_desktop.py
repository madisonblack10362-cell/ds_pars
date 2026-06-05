"""
Desktop GUI for DayZ News Monitor.
"""

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from logging import Handler, LogRecord, Formatter
from pathlib import Path

import customtkinter as ctk

from logger import logger


class LogCapture(Handler):
    def __init__(self):
        super().__init__()
        self._queue = queue.Queue(maxsize=2000)
        self.setFormatter(Formatter("%(message)s"))

    def emit(self, record: LogRecord) -> None:
        try:
            self._queue.put_nowait({
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": self.format(record),
            })
        except queue.Full:
            pass

    def get(self, timeout=0.1):
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


class DesktopGUI:

    BG = "#1a1a2e"
    BG2 = "#16213e"
    BG3 = "#0f3460"
    CARD = "#1e2a4a"
    ACCENT = "#58a6ff"
    GREEN = "#3fb950"
    RED = "#f85149"
    YELLOW = "#d29922"
    TEXT = "#e6edf3"
    TEXT2 = "#8b949e"
    TEXT3 = "#6e7681"
    INPUT_BG = "#0d1117"
    INPUT_BORDER = "#30363d"

    def __init__(self, config_path="config.json", log_capture=None, bot_instance=None):
        self.config_path = config_path
        self.log_capture = log_capture
        self.bot = bot_instance
        self._running = True

    def run(self):
        try:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except Exception:
            pass

        self.root = ctk.CTk()
        self.root.title("DayZ News Monitor")
        self.root.geometry("900x650")
        self.root.minsize(750, 500)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_header()
        self._build_tabs()
        self._load_and_fill_config()

        # Mousewheel: call tk.Tk.bind_all DIRECTLY to bypass CTkBaseClass
        # which raises AttributeError on bind_all/unbind_all.
        # tk.Tk.bind_all(self.root, ...) calls the original tkinter method,
        # skipping any override in the CTk class hierarchy.
        tk.Tk.bind_all(self.root, "<MouseWheel>", self._on_mousewheel, add="+")
        tk.Tk.bind_all(self.root, "<Button-4>", self._on_mousewheel, add="+")
        tk.Tk.bind_all(self.root, "<Button-5>", self._on_mousewheel, add="+")

        threading.Thread(target=self._poll_logs, daemon=True).start()
        self._started = datetime.now()
        threading.Thread(target=self._tick_uptime, daemon=True).start()
        self.root.mainloop()

    def _on_close(self):
        self._running = False
        try:
            self.root.destroy()
        except Exception:
            pass

    # ================================================================
    # Mousewheel
    # ================================================================

    def _on_mousewheel(self, event):
        """Scroll the log text when Логи tab is active."""
        try:
            if self.notebook.get() != "Логи":
                return
        except Exception:
            return
        try:
            tb = self._log_text
            if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
                tb.yview_scroll(-3, "units")
                self._user_scrolled = True
            elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
                tb.yview_scroll(3, "units")
                if tb.yview()[1] >= 1.0:
                    self._user_scrolled = False
        except Exception:
            pass

    # ================================================================
    # Header
    # ================================================================

    def _build_header(self):
        header = ctk.CTkFrame(self.root, fg_color=self.BG2, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="DayZ News Monitor",
            font=("Segoe UI", 16, "bold"),
            text_color=self.ACCENT,
        ).pack(side="left", padx=16)

        self.status_label = ctk.CTkLabel(
            header, text="Остановлен",
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

    # ================================================================
    # Tabs
    # ================================================================

    def _build_tabs(self):
        self.notebook = ctk.CTkTabview(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_dashboard(self.notebook.add("Дашборд"))
        self._build_settings(self.notebook.add("Настройки"))
        self._build_logs(self.notebook.add("Логи"))

    # === Dashboard ===

    def _build_dashboard(self, parent):
        status_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        status_frame.pack(fill="x", padx=8, pady=(8, 4))

        self._status_cards = {}
        for key, label in [
            ("discord", "Discord"),
            ("telegram", "Telegram"),
            ("ai", "AI Анализатор"),
            ("db", "База данных"),
            ("reddit", "Reddit"),
        ]:
            card = ctk.CTkFrame(status_frame, fg_color=self.BG2, width=160)
            card.pack(side="left", padx=4, pady=6, fill="y", expand=True)
            card.pack_propagate(False)

            ctk.CTkLabel(card, text=label, font=("Segoe UI", 11),
                        text_color=self.TEXT2).pack(pady=(8, 0))
            val = ctk.CTkLabel(card, text="Отключён", font=("Segoe UI", 12, "bold"),
                              text_color=self.TEXT3)
            val.pack(pady=(2, 2))
            info = ctk.CTkLabel(card, text="", font=("Segoe UI", 10),
                               text_color=self.TEXT3, wraplength=140)
            info.pack(pady=(0, 8))
            self._status_cards[key] = {"value": val, "info": info}

        counter_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        counter_frame.pack(fill="x", padx=8, pady=4)

        self._counter_labels = {}
        for key, label in [
            ("messages", "Сообщений собрано"),
            ("analyzed", "Проанализировано"),
            ("published", "Опубликовано"),
            ("duplicates", "Дубликатов"),
        ]:
            card = ctk.CTkFrame(counter_frame, fg_color=self.BG2)
            card.pack(side="left", padx=4, pady=6, fill="both", expand=True)
            ctk.CTkLabel(card, text=label, font=("Segoe UI", 10),
                        text_color=self.TEXT2).pack(pady=(8, 0))
            num = ctk.CTkLabel(card, text="0", font=("Segoe UI", 24, "bold"),
                              text_color=self.TEXT)
            num.pack(pady=(0, 8))
            self._counter_labels[key] = num

        info_frame = ctk.CTkFrame(parent, fg_color=self.CARD)
        info_frame.pack(fill="x", padx=8, pady=4)
        self._discord_detail = ctk.CTkLabel(
            info_frame, text="Discord: ожидание подключения...",
            font=("Segoe UI", 11), text_color=self.TEXT2, anchor="w")
        self._discord_detail.pack(fill="x", padx=12, pady=10)

    # === Settings ===

    def _build_settings(self, parent):
        canvas = ctk.CTkScrollableFrame(parent)
        canvas.pack(fill="both", expand=True, padx=8, pady=8)

        self._entries = {}
        self._toggles = {}

        sections = [
            ("Discord", [
                ("discord_token", "Discord Token", "Токен вашего аккаунта Discord"),
                ("sources_discord_guild_id", "Guild ID", "ID сервера"),
                ("sources_discord_channel_id", "Channel ID", "ID канала"),
            ]),
            ("Telegram", [
                ("telegram_bot_token", "Bot Token", "Токен от @BotFather"),
                ("telegram_channel_id", "Channel ID (Сводки)", "-100xxxxxxxxxx"),
                ("telegram_news_channel_id", "Channel ID (Новости)", "-100xxxxxxxxxx (пусто = как сводки)"),
            ]),
            ("AI / NVIDIA API", [
                ("openai_api_key", "API Key", "nvapi-..."),
                ("openai_base_url", "Base URL", "https://integrate.api.nvidia.com/v1"),
                ("openai_model", "Модель", "meta/llama-3.1-8b-instruct"),
            ]),
            ("Расписание", [
                ("check_interval_minutes", "Интервал проверки (мин)", "5"),
                ("reddit_check_interval_minutes", "Reddit интервал (мин)", "30"),
                ("reddit_min_score", "Reddit мин. рейтинг", "50"),
                ("daily_summary_hour", "Час сводки (UTC)", "10"),
                ("daily_summary_minute", "Минута сводки (UTC)", "0"),
                ("min_message_length", "Мин. длина сообщения", "20"),
                ("similarity_threshold", "Порог похожести", "0.85"),
                ("max_retries", "Макс. попыток", "3"),
                ("retry_delay_seconds", "Задержка между попытками (сек)", "10"),
                ("request_timeout_seconds", "Таймаут запроса (сек)", "30"),
                ("max_images_per_post", "Макс. фото в посте", "10"),
            ]),
            ("Веб-панель", [
                ("web_panel_url", "URL панели", "https://dayz-monitor-web.vercel.app"),
                ("web_panel_api_key", "API ключ панели", "Ключ для авторизации бота"),
            ]),
        ]

        for section_title, fields in sections:
            frame = ctk.CTkFrame(canvas, fg_color=self.CARD)
            frame.pack(fill="x", pady=(6, 3))

            ctk.CTkLabel(frame, text=section_title, font=("Segoe UI", 13, "bold"),
                        text_color=self.ACCENT).pack(anchor="w", padx=12, pady=(10, 4))

            for key, label, hint in fields:
                row = ctk.CTkFrame(frame, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=2)

                ctk.CTkLabel(row, text=label + ":", font=("Segoe UI", 11),
                            text_color=self.TEXT2, width=200, anchor="w").pack(side="left")

                is_secret = "token" in key or "key" in key
                entry = ctk.CTkEntry(
                    row, border_color=self.INPUT_BORDER, border_width=1,
                    text_color=self.TEXT, font=("Consolas", 12), width=350,
                    show="*" if is_secret else "",
                )
                entry.pack(side="left", padx=(0, 8), fill="x", expand=True)
                self._entries[key] = entry

                ctk.CTkLabel(row, text=hint, font=("Segoe UI", 10),
                            text_color=self.TEXT3, width=200, anchor="w").pack(side="left")

            if section_title == "Расписание":
                tf = ctk.CTkFrame(frame, fg_color="transparent")
                tf.pack(fill="x", padx=12, pady=(8, 10))
                for key, label in [
                    ("publish_high_priority", "Публиковать High"),
                    ("publish_medium_priority", "Публиковать Medium"),
                    ("publish_low_priority", "Публиковать Low"),
                ]:
                    var = tk.BooleanVar(value=False)
                    ctk.CTkCheckBox(tf, text=label, variable=var, font=("Segoe UI", 11),
                                   text_color=self.TEXT2, fg_color=self.INPUT_BORDER,
                                   hover_color=self.ACCENT).pack(side="left", padx=(0, 20))
                    self._toggles[key] = var

        bf = ctk.CTkFrame(canvas, fg_color="transparent")
        bf.pack(fill="x", pady=12)
        ctk.CTkButton(bf, text="Сохранить настройки", font=("Segoe UI", 12, "bold"),
                      fg_color=self.ACCENT, hover_color="#79b8ff", width=200, height=38,
                      command=self._save_config).pack(side="left", padx=4)
        ctk.CTkButton(bf, text="Перезагрузить", font=("Segoe UI", 12, "bold"),
                      fg_color="#2a3a5e", hover_color="#3a4a6e", width=200, height=38,
                      command=self._load_and_fill_config).pack(side="left", padx=4)

    # === Logs ===

    def _build_logs(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=self.CARD)
        bar.pack(fill="x", padx=8, pady=(8, 4))

        self._filter_btns = {}
        for level in ("ALL", "INFO", "WARNING", "ERROR", "DEBUG"):
            btn = ctk.CTkButton(bar, text=level, font=("Segoe UI", 11, "bold"),
                               width=70, height=30,
                               fg_color=self.ACCENT if level == "ALL" else self.BG3,
                               hover_color="#79b8ff",
                               command=lambda l=level: self._set_filter(l))
            btn.pack(side="left", padx=3, pady=6)
            self._filter_btns[level] = btn

        self._log_count = ctk.CTkLabel(bar, text="0 записей", font=("Segoe UI", 10),
                                       text_color=self.TEXT3)
        self._log_count.pack(side="right", padx=12)

        ctk.CTkButton(bar, text="Очистить", font=("Segoe UI", 10), width=80, height=30,
                      fg_color=self.BG3, hover_color=self.RED,
                      command=self._clear_logs).pack(side="right", padx=3, pady=6)

        # Log area: tk.Text + CTkScrollbar inside a CTkFrame.
        # No CTkTextbox — it inherits CTkBaseClass which blocks bind_all
        # and breaks mousewheel in CTkTabview on Windows.
        self._user_scrolled = False

        log_frame = ctk.CTkFrame(parent, fg_color=self.INPUT_BG)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._log_scrollbar = ctk.CTkScrollbar(
            log_frame,
            command=self._log_text_yview,
            fg_color=self.BG3,
            button_color=self.ACCENT,
            button_hover_color="#79b8ff",
        )
        self._log_scrollbar.pack(side="right", fill="y", padx=(0, 2), pady=2)

        self._log_text = tk.Text(
            log_frame, bg=self.INPUT_BG, fg=self.TEXT, font=("Consolas", 11),
            insertbackground=self.TEXT, selectbackground=self.BG3,
            selectforeground=self.TEXT,
            borderwidth=0, highlightthickness=0, wrap="word",
            cursor="arrow", takefocus=True,
            yscrollcommand=self._log_scrollbar.set,
        )
        self._log_text.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)

        # Block keyboard typing, allow selection + copy + navigation
        self._log_text.bind("<Key>", self._block_typing)

        # Colored tags
        self._log_text.tag_configure("TIME", foreground=self.TEXT3)
        self._log_text.tag_configure("LEVEL_INFO", foreground=self.ACCENT)
        self._log_text.tag_configure("LEVEL_WARNING", foreground=self.YELLOW)
        self._log_text.tag_configure("LEVEL_ERROR", foreground=self.RED)
        self._log_text.tag_configure("LEVEL_DEBUG", foreground=self.TEXT3)
        self._log_text.tag_configure("MSG", foreground=self.TEXT)

        self._total_lines = 0
        self._filter_level = "ALL"
        self._all_logs = []  # store all log entries for filtering

    def _log_text_yview(self, *args):
        """Route scrollbar commands to the tk.Text widget."""
        self._log_text.yview(*args)

    def _block_typing(self, event):
        """Block keyboard input but allow Ctrl combos and navigation."""
        if event.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                             "Alt_L", "Alt_R", "Super_L", "Super_R",
                             "Caps_Lock", "Tab",
                             "Left", "Right", "Up", "Down",
                             "Home", "End", "Next", "Prior",
                             "F1", "F2", "F3", "F4", "F5", "F6",
                             "F7", "F8", "F9", "F10", "F11", "F12",
                             "Insert", "Delete"):
            return
        if event.state & 0x4:  # Ctrl
            return
        if event.state & 0x1:  # Shift
            return
        return "break"

    # ================================================================
    # Config load / save
    # ================================================================

    def _load_and_fill_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[GUI] Ошибка загрузки конфига: {e}")
            return

        simple_keys = [
            "discord_token", "telegram_bot_token", "telegram_channel_id",
            "telegram_news_channel_id",
            "openai_api_key", "openai_base_url", "openai_model",
            "check_interval_minutes", "reddit_check_interval_minutes", "reddit_min_score",
            "daily_summary_hour", "daily_summary_minute",
            "min_message_length", "similarity_threshold",
            "max_retries", "retry_delay_seconds", "request_timeout_seconds",
            "max_images_per_post",
            "web_panel_url", "web_panel_api_key",
        ]
        for key in simple_keys:
            entry = self._entries.get(key)
            if entry and key in cfg:
                entry.delete(0, "end")
                entry.insert(0, str(cfg[key]))

        sources = cfg.get("sources", {})
        discord = sources.get("discord", {})
        for gui_key, cfg_key in [("sources_discord_guild_id", "guild_id"),
                                  ("sources_discord_channel_id", "channel_id")]:
            entry = self._entries.get(gui_key)
            if entry:
                entry.delete(0, "end")
                entry.insert(0, str(discord.get(cfg_key, "")))

        for key, var in self._toggles.items():
            var.set(cfg.get(key, False))

    def _save_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        simple_keys = [
            "discord_token", "telegram_bot_token", "telegram_channel_id",
            "telegram_news_channel_id",
            "openai_api_key", "openai_base_url", "openai_model",
            "check_interval_minutes", "reddit_check_interval_minutes", "reddit_min_score",
            "daily_summary_hour", "daily_summary_minute",
            "min_message_length", "similarity_threshold",
            "max_retries", "retry_delay_seconds", "request_timeout_seconds",
            "max_images_per_post",
            "web_panel_url", "web_panel_api_key",
        ]
        for key in simple_keys:
            entry = self._entries.get(key)
            if entry:
                val = entry.get()
                if key in ("check_interval_minutes", "reddit_check_interval_minutes", "daily_summary_hour", "daily_summary_minute",
                            "min_message_length", "max_retries", "retry_delay_seconds",
                            "request_timeout_seconds", "max_images_per_post", "reddit_min_score"):
                    try: val = int(val)
                    except ValueError: pass
                elif key == "similarity_threshold":
                    try: val = float(val)
                    except ValueError: pass
                cfg[key] = val

        if "sources" not in cfg:
            cfg["sources"] = {}
        if "discord" not in cfg["sources"]:
            cfg["sources"]["discord"] = {}
        cfg["sources"]["discord"]["guild_id"] = self._entries["sources_discord_guild_id"].get()
        cfg["sources"]["discord"]["channel_id"] = self._entries["sources_discord_channel_id"].get()

        for key, var in self._toggles.items():
            cfg[key] = var.get()

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            logger.info("Настройки сохранены через GUI")
            if self.bot:
                self.bot.config = cfg
        except Exception as e:
            logger.error("Ошибка сохранения настроек: %s", e)

    # ================================================================
    # Logs
    # ================================================================

    def _set_filter(self, level):
        self._filter_level = level
        for l, btn in self._filter_btns.items():
            btn.configure(fg_color=self.ACCENT if l == level else self.BG3)
        self._rebuild_log_display()

    def _rebuild_log_display(self):
        """Re-render log text widget showing only entries matching current filter."""
        try:
            tb = self._log_text
            tb.config(state="normal")
            tb.delete("1.0", "end")
            count = 0
            for entry in self._all_logs:
                if self._filter_level != "ALL" and entry["level"] != self._filter_level:
                    continue
                tag = f"LEVEL_{entry['level']}"
                if tag not in ("LEVEL_INFO", "LEVEL_WARNING", "LEVEL_ERROR", "LEVEL_DEBUG"):
                    tag = "MSG"
                tb.insert("end", f" {entry['time']} ", "TIME")
                tb.insert("end", f"{entry['level']:>8} ", tag)
                tb.insert("end", f"{entry['message']}\n", "MSG")
                count += 1
            tb.see("end")
            self._log_count.configure(text=f"{count} записей")
        except Exception:
            pass

    def _clear_logs(self):
        self._total_lines = 0
        self._all_logs.clear()
        self._log_text.delete("1.0", "end")
        self._log_count.configure(text="0 записей")

    def _poll_logs(self):
        while self._running:
            if not self.log_capture:
                threading.Event().wait(0.5)
                continue
            entry = self.log_capture.get(timeout=0.1)
            if not entry:
                continue

            level = entry["level"]

            # Store all entries for filtering
            self._all_logs.append(entry)
            if len(self._all_logs) > 2000:
                self._all_logs = self._all_logs[-1500:]
            self._total_lines = len(self._all_logs)

            # Only insert into text widget if it matches current filter
            if self._filter_level != "ALL" and level != self._filter_level:
                try:
                    self._log_count.configure(text=f"{self._count_visible()} записей")
                except Exception:
                    pass
                continue

            try:
                tb = self._log_text
                tb.insert("end", f" {entry['time']} ", "TIME")
                tag = f"LEVEL_{level}"
                if tag not in ("LEVEL_INFO", "LEVEL_WARNING", "LEVEL_ERROR", "LEVEL_DEBUG"):
                    tag = "MSG"
                tb.insert("end", f"{level:>8} ", tag)
                tb.insert("end", f"{entry['message']}\n", "MSG")
                if not self._user_scrolled:
                    tb.see("end")
                self._log_count.configure(text=f"{self._count_visible()} записей")
            except Exception:
                pass

    def _count_visible(self):
        """Count how many entries match current filter."""
        if self._filter_level == "ALL":
            return len(self._all_logs)
        return sum(1 for e in self._all_logs if e["level"] == self._filter_level)

    def _tick_uptime(self):
        while self._running:
            try:
                delta = datetime.now() - self._started
                h, r = divmod(int(delta.total_seconds()), 3600)
                m, s = divmod(r, 60)
                self.root.after(0, lambda txt=f"{h:02d}:{m:02d}:{s:02d}":
                               self.uptime_label.configure(text=txt))
            except Exception:
                break
            threading.Event().wait(1)

    # ================================================================
    # Public API
    # ================================================================

    def update_status(self, component, connected, info=""):
        card = self._status_cards.get(component)
        if not card:
            return
        try:
            def _apply():
                try:
                    if connected:
                        card["value"].configure(text="Подключён", text_color=self.GREEN)
                    else:
                        card["value"].configure(text="Отключён", text_color=self.TEXT3)
                    if info:
                        card["info"].configure(text=info)
                    if component == "discord":
                        if connected:
                            detail = f"Discord: подключён — {info}" if info else "Discord: подключён"
                        elif info:
                            detail = f"Discord: {info}"
                        else:
                            detail = "Discord: отключён"
                        self._discord_detail.configure(text=detail)
                except Exception:
                    pass
            self.root.after(0, _apply)
        except Exception:
            pass

    def set_status_running(self):
        try:
            self.root.after(0, lambda: self.status_label.configure(
                text="Работает", text_color=self.GREEN))
        except Exception:
            pass

    def set_bot_status(self, text, color=None):
        try:
            if color:
                self.root.after(0, lambda: self.status_label.configure(text=text, text_color=color))
            else:
                self.root.after(0, lambda: self.status_label.configure(text=text))
        except Exception:
            pass

    def update_uptime(self, seconds):
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        try:
            self.root.after(0, lambda: self.uptime_label.configure(
                text=f"{h:02d}:{m:02d}:{s:02d}"))
        except Exception:
            pass

    def append_log(self, level, message):
        if self.log_capture:
            try:
                self.log_capture._queue.put_nowait({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": f"[{level}] {message}",
                })
            except Exception:
                pass
