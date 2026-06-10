"""
Desktop GUI for DayZ News Monitor — Modern Design.
"""

import json
import queue
import re
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

    # ─── Цветовая палитра (GitHub Dark + accents) ─────────────────────────
    BG           = "#0d1117"
    BG_SURFACE   = "#161b22"
    BG_CARD      = "#1c2128"
    BG_ELEVATED  = "#21262d"
    BORDER       = "#30363d"
    ACCENT       = "#58a6ff"
    ACCENT_HOVER = "#79b8ff"
    GREEN        = "#3fb950"
    GREEN_BG     = "#12261e"
    RED          = "#f85149"
    RED_BG       = "#2d1014"
    YELLOW       = "#d29922"
    YELLOW_BG    = "#2d2200"
    ORANGE       = "#db6d28"
    TEXT         = "#e6edf3"
    TEXT2        = "#8b949e"
    TEXT3        = "#484f58"
    PURPLE       = "#bc8cff"

    # Иконки для карточек (Unicode)
    _ICONS = {
        "discord":   "\U0001F4AC",
        "telegram":  "\u2708",
        "ai":        "\U0001F9E0",
        "db":        "\U0001F4BE",
        "youtube":   "\u25B6",
        "workshop":  "\U0001F527",
        "patchnotes":"\U0001F4DD",
    }

    def __init__(self, config_path="config.json", log_capture=None, bot_instance=None):
        self.config_path = config_path
        self.log_capture = log_capture
        self.bot = bot_instance
        self._running = True
        self.root = None  # создаётся в run()

    # ================================================================
    # Main entry
    # ================================================================

    def run(self):
        try:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except Exception:
            pass

        self.root = ctk.CTk()
        self.root.title("DayZ News Monitor")
        self.root.geometry("960x700")
        self.root.minsize(800, 550)
        self.root.configure(fg_color=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_header()
        self._build_tabs()
        self._load_and_fill_config()

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
        try:
            if self.notebook.get() != "\u041b\u043e\u0433\u0438":
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
        header = ctk.CTkFrame(self.root, fg_color=self.BG_SURFACE, height=52, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Левая часть: название + статус
        left = ctk.CTkFrame(header, fg_color="transparent")
        left.pack(side="left", padx=16, fill="y")

        ctk.CTkLabel(
            left, text="\u2699  DayZ News Monitor",
            font=("Segoe UI", 15, "bold"),
            text_color=self.TEXT,
        ).pack(side="left", pady=14)

        # Правая часть: uptime + статус
        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=16, fill="y")

        self.status_label = ctk.CTkLabel(
            right, text="\u25cf  Остановлен",
            font=("Segoe UI", 11, "bold"),
            text_color=self.RED,
        )
        self.status_label.pack(side="right", padx=(12, 0), pady=14)

        # Uptime badge
        uptime_badge = ctk.CTkFrame(right, fg_color=self.BG_ELEVATED, corner_radius=6, width=90, height=26)
        uptime_badge.pack(side="right", padx=(0, 4), pady=14)
        uptime_badge.pack_propagate(False)

        self.uptime_label = ctk.CTkLabel(
            uptime_badge, text="00:00:00",
            font=("Consolas", 10),
            text_color=self.TEXT2,
        )
        self.uptime_label.pack(expand=True)

    # ================================================================
    # Tabs
    # ================================================================

    def _build_tabs(self):
        self.notebook = ctk.CTkTabview(self.root, fg_color=self.BG_SURFACE,
                                        segmented_button_fg_color=self.BG_ELEVATED,
                                        segmented_button_selected_color=self.ACCENT,
                                        segmented_button_selected_hover_color=self.ACCENT_HOVER,
                                        segmented_button_unselected_color=self.BG_ELEVATED,
                                        segmented_button_unselected_hover_color=self.BORDER)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(6, 8))

        self._build_dashboard(self.notebook.add("Дашборд"))
        self._build_settings(self.notebook.add("Настройки"))
        self._build_logs(self.notebook.add("Логи"))

    # ================================================================
    # Dashboard
    # ================================================================

    def _build_dashboard(self, parent):
        # Скроллируемый контейнер дашборда
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # ─── Строка кнопок ────────────────────────────────────────────
        btn_bar = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_bar.pack(fill="x", pady=(0, 8), padx=4)

        ctk.CTkButton(btn_bar, text="\u21bb  Перезагрузить бота",
                      font=("Segoe UI", 11, "bold"),
                      fg_color=self.ACCENT, hover_color=self.ACCENT_HOVER,
                      text_color="#ffffff", width=180, height=32, corner_radius=8,
                      command=self._restart_bot).pack(side="right", padx=4)

        # ─── Карточки статусов (grid 4x2) ─────────────────────────────
        status_outer = ctk.CTkFrame(scroll, fg_color=self.BG_CARD, corner_radius=10)
        status_outer.pack(fill="x", padx=4, pady=(0, 6))

        status_inner = ctk.CTkFrame(status_outer, fg_color="transparent")
        status_inner.pack(fill="x", padx=8, pady=8)

        # grid layout
        for c in range(4):
            status_inner.grid_columnconfigure(c, weight=1, uniform="col")
        for r in range(2):
            status_inner.grid_rowconfigure(r, weight=1, uniform="row")

        self._status_cards = {}
        _cards = [
            ("discord", "Discord"),
            ("telegram", "Telegram"),
            ("ai", "AI Анализатор"),
            ("db", "База данных"),
            ("youtube", "YouTube"),
            ("workshop", "Workshop"),
            ("patchnotes", "Патчноуты"),
        ]

        for idx, (key, label) in enumerate(_cards):
            row, col = divmod(idx, 4)
            icon = self._ICONS.get(key, "")

            card = ctk.CTkFrame(status_inner, fg_color=self.BG_ELEVATED, corner_radius=8)
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

            # Верхняя строка: иконка + название
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(8, 0))

            ctk.CTkLabel(top, text=f"{icon}  {label}", font=("Segoe UI", 11),
                        text_color=self.TEXT2).pack(side="left")

            # Индикатор статуса (точка)
            val = ctk.CTkLabel(card, text="\u25cf  Отключён", font=("Segoe UI", 10),
                              text_color=self.TEXT3)
            val.pack(anchor="w", padx=10, pady=(4, 0))

            # Инфо-строка
            info = ctk.CTkLabel(card, text="", font=("Segoe UI", 9),
                               text_color=self.TEXT3, wraplength=180, anchor="w")
            info.pack(fill="x", padx=10, pady=(2, 8))

            self._status_cards[key] = {"value": val, "info": info}

        # ─── Счётчики ─────────────────────────────────────────────────
        counter_outer = ctk.CTkFrame(scroll, fg_color=self.BG_CARD, corner_radius=10)
        counter_outer.pack(fill="x", padx=4, pady=(0, 6))

        counter_inner = ctk.CTkFrame(counter_outer, fg_color="transparent")
        counter_inner.pack(fill="x", padx=8, pady=8)

        for c in range(4):
            counter_inner.grid_columnconfigure(c, weight=1, uniform="ccol")

        _counters = [
            ("messages",   "Сообщений",     self.ACCENT),
            ("analyzed",   "Проанализировано", self.PURPLE),
            ("published",  "Опубликовано",   self.GREEN),
            ("duplicates", "Дубликатов",     self.YELLOW),
        ]

        self._counter_labels = {}
        for idx, (key, label, color) in enumerate(_counters):
            card = ctk.CTkFrame(counter_inner, fg_color=self.BG_ELEVATED, corner_radius=8)
            card.grid(row=0, column=idx, padx=4, pady=4, sticky="nsew")

            ctk.CTkLabel(card, text=label, font=("Segoe UI", 10),
                        text_color=self.TEXT2).pack(pady=(10, 0))
            num = ctk.CTkLabel(card, text="0", font=("Segoe UI", 22, "bold"),
                              text_color=color)
            num.pack(pady=(0, 10))
            self._counter_labels[key] = num

        # ─── Инфо-панель источников ──────────────────────────────────
        info_outer = ctk.CTkFrame(scroll, fg_color=self.BG_CARD, corner_radius=10)
        info_outer.pack(fill="x", padx=4, pady=(0, 4))

        info_header = ctk.CTkFrame(info_outer, fg_color="transparent")
        info_header.pack(fill="x", padx=12, pady=(10, 0))
        ctk.CTkLabel(info_header, text="\U0001F310  Статус источников",
                    font=("Segoe UI", 11, "bold"), text_color=self.TEXT2).pack(side="left")

        self._source_detail = ctk.CTkLabel(
            info_outer, text="Ожидание запуска...",
            font=("Segoe UI", 10), text_color=self.TEXT3, anchor="w",
            wraplength=880, justify="left")
        self._source_detail.pack(fill="x", padx=12, pady=(4, 12))

    # ================================================================
    # Settings
    # ================================================================

    def _build_settings(self, parent):
        canvas = ctk.CTkScrollableFrame(parent, fg_color="transparent")
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
                ("telegram_news_channel_id", "Channel ID (Новости)", "-100xxxxxxxxxx"),
            ]),
            ("AI / NVIDIA API", [
                ("openai_api_key", "API Key", "nvapi-..."),
                ("openai_base_url", "Base URL", "https://integrate.api.nvidia.com/v1"),
                ("openai_model", "Модель", "meta/llama-3.1-8b-instruct"),
            ]),
            ("Расписание", [
                ("check_interval_minutes", "Интервал проверки (мин)", "5"),
                ("daily_summary_hour", "Час сводки (UTC)", "10"),
                ("daily_summary_minute", "Минута сводки (UTC)", "0"),
                ("min_message_length", "Мин. длина сообщения", "20"),
                ("similarity_threshold", "Порог похожести", "0.85"),
                ("max_retries", "Макс. попыток", "3"),
                ("retry_delay_seconds", "Задержка между попытками (сек)", "10"),
                ("request_timeout_seconds", "Таймаут запроса (сек)", "30"),
                ("max_images_per_post", "Макс. фото в посте", "10"),
            ]),
            ("Steam Workshop", [
                ("workshop_interval_minutes", "Интервал проверки (мин)", "60"),
                ("workshop_min_subscriptions", "Мин. подписчиков мода", "100"),
                ("steam_api_key", "Steam API Key", "Необязательно"),
            ]),
            ("Патчноуты", [
                ("patchnotes_interval_minutes", "Интервал проверки (мин)", "30"),
            ]),
            ("YouTube", [
                ("youtube_interval_hours", "Интервал проверки (часы)", "2"),
                ("youtube_min_views", "Мин. просмотров", "0"),
                ("youtube_min_likes", "Мин. лайков", "0"),
                ("youtube_max_per_check", "Макс. видео за проверку", "5"),
            ]),
            ("YouTube Каналы", []),
            ("Веб-панель", [
                ("web_panel_url", "URL панели", "https://dayz-monitor-web.vercel.app"),
                ("web_panel_api_key", "API ключ панели", "Ключ авторизации бота"),
            ]),
        ]

        for section_title, fields in sections:
            self._build_section(canvas, section_title, fields)

        # Кнопки внизу
        bf = ctk.CTkFrame(canvas, fg_color="transparent")
        bf.pack(fill="x", pady=(12, 8))

        ctk.CTkButton(bf, text="\u2714  Сохранить",
                      font=("Segoe UI", 12, "bold"),
                      fg_color=self.GREEN, hover_color="#4cc95f",
                      text_color="#ffffff", width=160, height=36, corner_radius=8,
                      command=self._save_config).pack(side="left", padx=4)

        ctk.CTkButton(bf, text="\u21bb  Перезагрузить",
                      font=("Segoe UI", 12, "bold"),
                      fg_color=self.BG_ELEVATED, hover_color=self.BORDER,
                      text_color=self.TEXT2, width=160, height=36, corner_radius=8,
                      command=self._load_and_fill_config).pack(side="left", padx=4)

    def _build_section(self, parent, title, fields):
        """Строит одну секцию настроек с красивым заголовком."""
        frame = ctk.CTkFrame(parent, fg_color=self.BG_CARD, corner_radius=10)
        frame.pack(fill="x", pady=(4, 2))

        # Заголовок секции
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(10, 2))

        ctk.CTkLabel(header, text=title, font=("Segoe UI", 12, "bold"),
                    text_color=self.ACCENT).pack(side="left")

        # Разделитель
        sep = ctk.CTkFrame(frame, fg_color=self.BORDER, height=1)
        sep.pack(fill="x", padx=14, pady=(4, 6))

        # Тогглы
        if title == "Steam Workshop":
            self._add_toggle(frame, "workshop_enabled", "Включить монитор Steam Workshop")
        elif title == "Патчноуты":
            self._add_toggle(frame, "patchnotes_enabled", "Включить монитор патчноутов")
        elif title == "YouTube":
            self._add_toggle(frame, "youtube_enabled", "Включить YouTube монитор")
            self._add_toggle(frame, "youtube_download_shorts", "Скачивать шортсы")
            self._add_toggle(frame, "youtube_russian_only", "Только русскоязычные видео")
            self._add_toggle(frame, "youtube_shorts_only", "Только Shorts (<=90с)")
        elif title == "YouTube Каналы":
            self._build_youtube_channels_section(frame)
        elif title == "Веб-панель":
            self._add_toggle(frame, "moderation_notifications", "Уведомления о модерации в Telegram")

        # Поля ввода
        for key, label, hint in fields:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)

            ctk.CTkLabel(row, text=label, font=("Segoe UI", 11),
                        text_color=self.TEXT2, width=180, anchor="w").pack(side="left")

            is_secret = "token" in key or "key" in key
            entry = ctk.CTkEntry(
                row, border_color=self.BORDER, border_width=1,
                text_color=self.TEXT, font=("Consolas", 11),
                fg_color=self.BG_ELEVATED,
                show="\u2022" if is_secret else "",
                height=32, corner_radius=6,
            )
            entry.pack(side="left", padx=(8, 8), fill="x", expand=True)
            self._bind_paste(entry)
            self._entries[key] = entry

            ctk.CTkLabel(row, text=hint, font=("Segoe UI", 9),
                        text_color=self.TEXT3, width=160, anchor="w").pack(side="left")

        # Тогглы для Расписание
        if title == "Расписание":
            toggle_frame = ctk.CTkFrame(frame, fg_color="transparent")
            toggle_frame.pack(fill="x", padx=14, pady=(6, 10))
            for key, label in [
                ("publish_high_priority", "High"),
                ("publish_medium_priority", "Medium"),
                ("publish_low_priority", "Low"),
            ]:
                var = tk.BooleanVar(value=False)
                ctk.CTkCheckBox(
                    toggle_frame, text=f"Публиковать {label}",
                    variable=var, font=("Segoe UI", 11),
                    text_color=self.TEXT2, fg_color=self.BORDER,
                    hover_color=self.ACCENT, checkbox_width=18, checkbox_height=18,
                    corner_radius=4,
                ).pack(side="left", padx=(0, 24))
                self._toggles[key] = var

    def _add_toggle(self, parent, key, label):
        tf = ctk.CTkFrame(parent, fg_color="transparent")
        tf.pack(fill="x", padx=14, pady=(2, 6))
        var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            tf, text=label,
            variable=var, font=("Segoe UI", 11),
            text_color=self.TEXT2, fg_color=self.BORDER,
            hover_color=self.ACCENT, checkbox_width=18, checkbox_height=18,
            corner_radius=4,
        ).pack(anchor="w")
        self._toggles[key] = var

    def _build_youtube_channels_section(self, parent):
        """Секция управления YouTube-каналами: список + добавление/удаление."""
        # Описание
        hint_frame = ctk.CTkFrame(parent, fg_color="transparent")
        hint_frame.pack(fill="x", padx=14, pady=(6, 4))
        ctk.CTkLabel(
            hint_frame,
            text="Добавляйте YouTube-каналы для парсинга по Channel ID или URL",
            font=("Segoe UI", 10),
            text_color=self.TEXT3,
        ).pack(anchor="w")
        ctk.CTkLabel(
            hint_frame,
            text="Пример: UCvQPcPcEzzMPTjTMzGCRN0g или https://www.youtube.com/@channel",
            font=("Segoe UI", 9),
            text_color=self.TEXT3,
        ).pack(anchor="w")

        # Поле ввода + кнопка добавления
        add_row = ctk.CTkFrame(parent, fg_color="transparent")
        add_row.pack(fill="x", padx=14, pady=(4, 6))

        self._yt_channel_entry = ctk.CTkEntry(
            add_row,
            border_color=self.BORDER, border_width=1,
            text_color=self.TEXT, font=("Consolas", 11),
            fg_color=self.BG_ELEVATED,
            height=32, corner_radius=6,
            placeholder_text="Channel ID или URL YouTube...",
        )
        self._yt_channel_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._bind_paste(self._yt_channel_entry)

        # Кнопка "Вставить" — через PowerShell + запись во внутренний и внешний виджет
        def _paste_channel():
            try:
                import subprocess
                r = subprocess.run(
                    ["powershell", "-command", "Get-Clipboard"],
                    capture_output=True, text=True, timeout=5
                )
                text = r.stdout.strip()
                if not text:
                    return
                # Пишем и во внутренний _entry и в CTkEntry
                self._yt_channel_entry.delete(0, "end")
                try:
                    w = getattr(self._yt_channel_entry, "_entry", None)
                    if w:
                        w.delete(0, "end")
                        w.insert(0, text)
                    else:
                        self._yt_channel_entry.insert(0, text)
                except Exception:
                    self._yt_channel_entry.insert(0, text)
            except Exception as e:
                self.append_log("ERROR", f"Вставка: {e}")

        ctk.CTkButton(
            add_row, text="📋 Вставить", width=90,
            font=("Segoe UI", 10),
            command=_paste_channel,
        ).pack(side="left", padx=(0, 8))



        ctk.CTkButton(
            add_row, text="+ Добавить",
            font=("Segoe UI", 11, "bold"),
            fg_color=self.GREEN, hover_color="#4cc95f",
            text_color="#ffffff", width=100, height=32, corner_radius=8,
            command=self._add_youtube_channel,
        ).pack(side="left")

        # Список каналов (скроллируемый)
        list_frame = ctk.CTkFrame(parent, fg_color=self.BG_ELEVATED, corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10), ipady=4)

        self._yt_channels_listbox_frame = ctk.CTkScrollableFrame(
            list_frame, fg_color="transparent", height=180,
        )
        self._yt_channels_listbox_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._yt_channel_widgets = []

    def _add_youtube_channel(self):
        """Добавляет канал в список и сохраняет в config."""
        # Читаем текст: сначала из CTkEntry, fallback на внутренний _entry
        raw = self._yt_channel_entry.get().strip()
        if not raw:
            try:
                w = getattr(self._yt_channel_entry, "_entry", None)
                if w:
                    raw = w.get().strip()
            except Exception:
                pass
        if not raw:
            self.append_log("WARNING", "YouTube: поле канала пустое")
            return

        # Парсим ID из URL или текста
        channel_id = self._parse_youtube_channel_id(raw)
        if not channel_id:
            self.append_log("WARNING", "YouTube: не удалось извлечь Channel ID из: " + raw)
            return

        # Загружаем текущий список из конфига
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

        channels = cfg.get("youtube_channels", [])
        if not isinstance(channels, list):
            channels = []

        # Проверяем на дубликат
        for ch in channels:
            ch_id = ch.get("id", "") if isinstance(ch, dict) else str(ch)
            if ch_id == channel_id:
                self.append_log("WARNING", f"YouTube: канал {channel_id} уже есть в списке")
                return

        # Добавляем
        channels.append({"id": channel_id, "name": ""})
        cfg["youtube_channels"] = channels

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            logger.info("YouTube: добавлен канал %s (%s)", channel_id, name or "без имени")
            self.append_log("INFO", f"YouTube: добавлен канал {name or channel_id}")
        except Exception as e:
            logger.error("Ошибка сохранения канала: %s", e)
            self.append_log("ERROR", f"Ошибка сохранения: {e}")
            return

        # Очищаем оба виджета
        self._yt_channel_entry.delete(0, "end")
        self._yt_name_entry.delete(0, "end")
        try:
            getattr(self._yt_channel_entry, "_entry", None).delete(0, "end")
        except Exception:
            pass


        # Обновляем список в GUI
        self._refresh_youtube_channels_list(cfg)

        # Обновляем каналы в youtube_monitor
        try:
            from youtube_monitor import load_youtube_channels
            load_youtube_channels(cfg)
        except Exception:
            pass

    @staticmethod
    def _get_inner(e):
        """Возвращает внутренний tk.Entry из CTkEntry."""
        return getattr(e, "_entry", e)

    @staticmethod
    def _bind_paste(entry):
        """Ctrl+V/A/C/X для CTkEntry — через внутренний tk.Entry."""
        def _inner():
            return getattr(entry, "_entry", entry)

        def do_paste(event=None):
            try:
                w = _inner()
                w.delete("sel.first", "sel.last")
                text = w.clipboard_get()
                w.insert("insert", text)
            except Exception:
                pass
            return "break"

        def do_copy(event=None):
            try:
                w = _inner()
                text = w.selection_get()
                w.clipboard_clear()
                w.clipboard_append(text)
            except Exception:
                pass
            return "break"

        def do_cut(event=None):
            try:
                w = _inner()
                text = w.selection_get()
                w.clipboard_clear()
                w.clipboard_append(text)
                w.delete("sel.first", "sel.last")
            except Exception:
                pass
            return "break"

        def do_selall(event=None):
            try:
                w = _inner()
                w.focus_set()
                w.select_range(0, "end")
            except Exception:
                pass
            return "break"

        for seq in ("<Control-v>", "<Control-V>", "<Control-c>", "<Control-C>",
                    "<Control-x>", "<Control-X>", "<Control-a>", "<Control-A>"):
            entry.bind(seq, None)  # снимаем дефолтный биндинг
        entry.bind("<Control-v>", do_paste)
        entry.bind("<Control-V>", do_paste)
        entry.bind("<Control-c>", do_copy)
        entry.bind("<Control-C>", do_copy)
        entry.bind("<Control-x>", do_cut)
        entry.bind("<Control-X>", do_cut)
        entry.bind("<Control-a>", do_selall)
        entry.bind("<Control-A>", do_selall)
        # Биндим и на внутренний виджет
        inner = _inner()
        inner.bind("<Control-v>", do_paste)
        inner.bind("<Control-V>", do_paste)
        inner.bind("<Control-c>", do_copy)
        inner.bind("<Control-C>", do_copy)
        inner.bind("<Control-x>", do_cut)
        inner.bind("<Control-X>", do_cut)
        inner.bind("<Control-a>", do_selall)
        inner.bind("<Control-A>", do_selall)

    def _parse_youtube_channel_id(self, text: str) -> str:
        """Извлекает YouTube Channel ID из строки (ID напрямую, URL, @handle)."""
        text = text.strip()

        # Прямой Channel ID (начинается с UC, 24 символа)
        if re.match(r"^UC[\w-]{22}$", text):
            return text

        # YouTube URL с channel_id
        m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", text)
        if m:
            return m.group(1)

        # YouTube URL с @handle — сохраняем как есть (бот сам резолвнет при парсинге)
        m = re.search(r"youtube\.com/@([\w.-]+)", text)
        if m:
            handle = m.group(1)
            # Сохраняем как @handle — youtube_monitor попробует resolving
            return f"@{handle}"

        # Просто @handle
        if text.startswith("@") and len(text) > 1:
            return text

        return ""

    def _refresh_youtube_channels_list(self, cfg: dict):
        """Обновляет визуальный список каналов в GUI."""
        # Очищаем старые виджеты
        for w in self._yt_channel_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._yt_channel_widgets.clear()

        channels = cfg.get("youtube_channels", [])
        if not channels:
            ctk.CTkLabel(
                self._yt_channels_listbox_frame,
                text="Нет добавленных каналов (используются каналы по умолчанию)",
                font=("Segoe UI", 10),
                text_color=self.TEXT3,
            ).pack(anchor="w", padx=8, pady=8)
            self._yt_channel_widgets.append(
                self._yt_channels_listbox_frame.winfo_children()[-1]
            )
            return

        for idx, ch in enumerate(channels):
            if isinstance(ch, dict):
                ch_id = ch.get("id", "?")
                ch_name = ch.get("name", "")
            else:
                ch_id = str(ch)
                ch_name = ""

            row = ctk.CTkFrame(self._yt_channels_listbox_frame, fg_color=self.BG_CARD, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)

            # Если есть имя — показываем "Имя (ID)", иначе просто ID
            if ch_name:
                display = f"  {ch_name}  ({ch_id})"
            else:
                display = f"  {ch_id}"

            ctk.CTkLabel(
                row,
                text=display,
                font=("Consolas", 10),
                text_color=self.TEXT2,
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(8, 0), pady=6)

            # Кнопка удаления
            btn = ctk.CTkButton(
                row, text="✕",
                font=("Segoe UI", 11),
                fg_color=self.RED_BG, hover_color=self.RED,
                text_color=self.RED, width=28, height=28, corner_radius=6,
                command=lambda i=idx: self._remove_youtube_channel(i),
            )
            btn.pack(side="right", padx=(0, 8), pady=6)

            self._yt_channel_widgets.append(row)

    def _remove_youtube_channel(self, index: int):
        """Удаляет канал из списка по индексу."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            return

        channels = cfg.get("youtube_channels", [])
        if not isinstance(channels, list) or index >= len(channels):
            return

        removed = channels.pop(index)
        ch_info = removed.get("name", removed.get("id", "?")) if isinstance(removed, dict) else str(removed)
        cfg["youtube_channels"] = channels

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            logger.info("YouTube: удалён канал %s", ch_info)
            self.append_log("INFO", f"YouTube: удалён канал {ch_info}")
        except Exception as e:
            logger.error("Ошибка удаления канала: %s", e)
            return

        self._refresh_youtube_channels_list(cfg)

        try:
            from youtube_monitor import load_youtube_channels
            load_youtube_channels(cfg)
        except Exception:
            pass

    # ================================================================
    # Logs
    # ================================================================

    def _build_logs(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=self.BG_CARD, corner_radius=10)
        bar.pack(fill="x", padx=4, pady=(4, 4))

        bar_inner = ctk.CTkFrame(bar, fg_color="transparent")
        bar_inner.pack(fill="x", padx=10, pady=8)

        self._filter_btns = {}
        for level in ("ALL", "INFO", "WARNING", "ERROR", "DEBUG"):
            btn = ctk.CTkButton(
                bar_inner, text=level,
                font=("Segoe UI", 10, "bold"), width=64, height=28,
                corner_radius=6,
                fg_color=self.ACCENT if level == "ALL" else self.BG_ELEVATED,
                hover_color=self.ACCENT_HOVER,
                text_color="#ffffff" if level == "ALL" else self.TEXT2,
                command=lambda l=level: self._set_filter(l))
            btn.pack(side="left", padx=2)
            self._filter_btns[level] = btn

        self._log_count = ctk.CTkLabel(bar_inner, text="0 записей",
                                       font=("Segoe UI", 9), text_color=self.TEXT3)
        self._log_count.pack(side="right", padx=(8, 0))

        ctk.CTkButton(bar_inner, text="Очистить", font=("Segoe UI", 9),
                      width=70, height=28, corner_radius=6,
                      fg_color=self.BG_ELEVATED, hover_color=self.RED,
                      text_color=self.TEXT2,
                      command=self._clear_logs).pack(side="right", padx=2)

        # Log area
        self._user_scrolled = False

        log_frame = ctk.CTkFrame(parent, fg_color=self.BG_CARD, corner_radius=10)
        log_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self._log_scrollbar = ctk.CTkScrollbar(
            log_frame, command=self._log_text_yview,
            fg_color=self.BG_ELEVATED,
            button_color=self.BORDER,
            button_hover_color=self.TEXT3,
        )
        self._log_scrollbar.pack(side="right", fill="y", padx=(0, 4), pady=4)

        self._log_text = tk.Text(
            log_frame, bg=self.BG_SURFACE, fg=self.TEXT, font=("Consolas", 10),
            insertbackground=self.TEXT, selectbackground=self.BG_ELEVATED,
            selectforeground=self.TEXT,
            borderwidth=0, highlightthickness=0, wrap="word",
            cursor="arrow", takefocus=True,
            yscrollcommand=self._log_scrollbar.set,
            padx=8, pady=6,
        )
        self._log_text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        self._log_text.bind("<Key>", self._block_typing)
        self._log_text.bind("<Control-c>", self._copy_log_selection)
        self._log_text.bind("<Control-C>", self._copy_log_selection)
        self._log_text.bind("<Control-a>", self._select_all_logs)
        self._log_text.bind("<Control-A>", self._select_all_logs)

        # Tags
        self._log_text.tag_configure("TIME", foreground=self.TEXT3)
        self._log_text.tag_configure("LEVEL_INFO", foreground=self.ACCENT)
        self._log_text.tag_configure("LEVEL_WARNING", foreground=self.YELLOW)
        self._log_text.tag_configure("LEVEL_ERROR", foreground=self.RED)
        self._log_text.tag_configure("LEVEL_DEBUG", foreground=self.TEXT3)
        self._log_text.tag_configure("MSG", foreground=self.TEXT)

        self._total_lines = 0
        self._filter_level = "ALL"
        self._all_logs = []

    def _log_text_yview(self, *args):
        self._log_text.yview(*args)

    def _copy_log_selection(self, event=None):
        """Копирует выделенный текст из лога в буфер обмена."""
        try:
            text = self._log_text.selection_get()
            self._log_text.clipboard_clear()
            self._log_text.clipboard_append(text)
        except Exception:
            pass
        return "break"

    def _select_all_logs(self, event=None):
        """Выделяет весь текст в логе."""
        self._log_text.tag_add("sel", "1.0", "end")
        return "break"

    def _block_typing(self, event):
        if event.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                             "Alt_L", "Alt_R", "Super_L", "Super_R",
                             "Caps_Lock", "Tab",
                             "Left", "Right", "Up", "Down",
                             "Home", "End", "Next", "Prior",
                             "F1", "F2", "F3", "F4", "F5", "F6",
                             "F7", "F8", "F9", "F10", "F11", "F12",
                             "Insert", "Delete"):
            return
        if event.state & 0x4:
            return
        if event.state & 0x1:
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

        try:
            simple_keys = [
                "discord_token", "telegram_bot_token", "telegram_channel_id",
                "telegram_news_channel_id",
                "openai_api_key", "openai_base_url", "openai_model",
                "check_interval_minutes",
                "daily_summary_hour", "daily_summary_minute",
                "min_message_length", "similarity_threshold",
                "max_retries", "retry_delay_seconds", "request_timeout_seconds",
                "max_images_per_post",
                "web_panel_url", "web_panel_api_key",
                "workshop_interval_minutes", "workshop_min_subscriptions", "steam_api_key",
                "patchnotes_interval_minutes",
                "youtube_interval_hours", "youtube_min_views", "youtube_min_likes", "youtube_max_per_check",
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
                if key in ("workshop_enabled", "patchnotes_enabled", "moderation_notifications",
                            "youtube_enabled", "youtube_download_shorts",
                            "youtube_russian_only", "youtube_shorts_only"):
                    default = True
                else:
                    default = False
                var.set(cfg.get(key, default))

            # Загружаем список YouTube-каналов
            if hasattr(self, '_yt_channels_listbox_frame') and self._yt_channels_listbox_frame:
                self._refresh_youtube_channels_list(cfg)

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[GUI] Ошибка заполнения полей: {e}")

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
            "check_interval_minutes",
            "daily_summary_hour", "daily_summary_minute",
            "min_message_length", "similarity_threshold",
            "max_retries", "retry_delay_seconds", "request_timeout_seconds",
            "max_images_per_post",
            "web_panel_url", "web_panel_api_key",
            "workshop_interval_minutes", "workshop_min_subscriptions", "steam_api_key",
            "patchnotes_interval_minutes",
            "youtube_interval_hours", "youtube_min_views", "youtube_min_likes", "youtube_max_per_check",
        ]
        for key in simple_keys:
            entry = self._entries.get(key)
            if entry:
                val = entry.get()
                if key in ("check_interval_minutes", "daily_summary_hour", "daily_summary_minute",
                            "min_message_length", "max_retries", "retry_delay_seconds",
                            "request_timeout_seconds", "max_images_per_post",
                            "workshop_interval_minutes", "workshop_min_subscriptions", "patchnotes_interval_minutes",
                            "youtube_interval_hours", "youtube_min_views", "youtube_min_likes", "youtube_max_per_check"):
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
            if l == level:
                btn.configure(fg_color=self.ACCENT, text_color="#ffffff")
            else:
                btn.configure(fg_color=self.BG_ELEVATED, text_color=self.TEXT2)
        self._rebuild_log_display()

    def _rebuild_log_display(self):
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
            self._all_logs.append(entry)
            if len(self._all_logs) > 2000:
                self._all_logs = self._all_logs[-1500:]
            self._total_lines = len(self._all_logs)

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

        def _apply():
            try:
                if connected:
                    card["value"].configure(text="\u25cf  Подключён", text_color=self.GREEN)
                else:
                    card["value"].configure(text="\u25cf  Отключён", text_color=self.TEXT3)
                if info:
                    card["info"].configure(text=info)
            except Exception:
                pass
        self._safe_after(_apply)

    def _safe_after(self, callback, delay=0):
        """Безопасный вызов root.after — ждёт если root ещё не создан."""
        waited = 0
        while self.root is None and waited < 10:
            threading.Event().wait(0.5)
            waited += 0.5
        if self.root is None:
            return
        try:
            self.root.after(delay, callback)
        except Exception:
            pass

    def set_status_starting(self):
        self._safe_after(lambda: self.status_label.configure(
            text="\u25cf  Запуск...", text_color=self.YELLOW))

    def set_status_running(self):
        self._safe_after(lambda: self.status_label.configure(
            text="\u25cf  Работает", text_color=self.GREEN))

    def set_bot_status(self, text, color=None):
        def _apply():
            try:
                if color:
                    self.status_label.configure(text=text, text_color=color)
                else:
                    self.status_label.configure(text=text)
            except Exception:
                pass
        self._safe_after(_apply)

    def update_counters(self, messages=0, analyzed=0, published=0, duplicates=0):
        def _apply():
            try:
                labels = self._counter_labels
                if "messages" in labels:
                    labels["messages"].configure(text=str(messages))
                if "analyzed" in labels:
                    labels["analyzed"].configure(text=str(analyzed))
                if "published" in labels:
                    labels["published"].configure(text=str(published))
                if "duplicates" in labels:
                    labels["duplicates"].configure(text=str(duplicates))
            except Exception:
                pass
        self._safe_after(_apply)

    def update_source_detail(self, text):
        self._safe_after(lambda: self._source_detail.configure(text=text))

    def update_uptime(self, seconds):
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        self._safe_after(lambda: self.uptime_label.configure(
            text=f"{h:02d}:{m:02d}:{s:02d}"))

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

    def _restart_bot(self):
        """Перезапускает весь процесс бота (включая GUI)."""
        import os
        import sys
        try:
            self.append_log("INFO", "Перезапуск бота...")
            self._safe_after(lambda: self.status_label.configure(
                text="\u25cf  Перезапуск...", text_color=self.YELLOW))
            # Даём время обновить GUI
            threading.Event().wait(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"[GUI] Ошибка перезапуска: {e}")
            self.append_log("ERROR", f"Ошибка перезапуска: {e}")
