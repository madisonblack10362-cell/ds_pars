"""
Десктопный GUI для DayZ News Monitor.
CustomTkinter — 3 вкладки: Dashboard, Settings, Logs.
Запускается ТОЛЬКО в главном потоке (требование tkinter на Windows).
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Optional

import customtkinter as ctk


class DesktopGUI:
    def __init__(self, config_path: str = "config.json", bot_instance=None):
        self.config_path = config_path
        self.bot_instance = bot_instance
        self.config: dict = {}
        self.log_queue = queue.Queue()

        # Appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Root window — создаём СРАЗУ в конструкторе (главный поток!)
        self.root = ctk.CTk()
        self.root.title("DayZ News Monitor")
        self.root.geometry("900x650")
        self.root.minsize(800, 550)

        # Загружаем конфиг ДО построения UI
        self._load_config()

        # Строим интерфейс
        self._build_ui()

        # Загружаем значения из конфига в поля
        self._populate_settings_from_config()

        # Запускаем фоновый поток для чтения логов
        self._log_poll_running = True
        self._log_thread = threading.Thread(target=self._poll_logs, daemon=True)
        self._log_thread.start()

        # При закрытии окна
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Конфиг
    # ------------------------------------------------------------------

    def _load_config(self):
        """Загружает config.json в self.config."""
        # Сначала пробуем взять конфиг из bot_instance (там он уже загружен)
        if self.bot_instance and hasattr(self.bot_instance, 'config') and self.bot_instance.config:
            self.config = self.bot_instance.config
            print(f"[GUI] Конфиг взят из bot_instance ({len(self.config)} ключей)")
            return

        # Иначе читаем из файла
        config_file = Path(self.config_path).resolve()
        full_path = str(config_file)
        print(f"[GUI] Ищу конфиг по пути: {full_path}")
        print(f"[GUI] Текущая директория: {os.getcwd()}")

        if config_file.exists():
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                keys = list(self.config.keys())
                print(f"[GUI] Конфиг загружен: {len(keys)} ключей: {keys}")
            except Exception as e:
                print(f"[GUI] Ошибка загрузки конфига: {e}")
                self.config = {}
        else:
            # Пробуем другие пути
            alt_paths = [
                Path(os.getcwd()) / "config.json",
                Path(sys.argv[0]).parent / "config.json" if sys.argv[0] else None,
                Path.home() / "config.json",
            ]
            found = False
            for alt in alt_paths:
                if alt and alt.exists():
                    try:
                        with open(str(alt), "r", encoding="utf-8") as f:
                            self.config = json.load(f)
                        print(f"[GUI] Конфиг найден по альтернативному пути: {alt}")
                        self.config_path = str(alt)
                        found = True
                        break
                    except Exception:
                        pass

            if not found:
                print(f"[GUI] Файл конфига НЕ НАЙДЕН нигде!")
                print(f"[GUI] Проверял: {full_path}")
                self.config = {}

    def _save_config(self):
        """Сохраняет текущие значения полей обратно в config.json."""
        # Читаем существующие значения, которые НЕ управляются через GUI
        cfg = {}
        config_file = Path(self.config_path)
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass

        # Обновляем значения из полей GUI
        cfg["discord_token"] = self.settings_vars["discord_token"].get()
        cfg["telegram_bot_token"] = self.settings_vars["telegram_bot_token"].get()
        cfg["telegram_channel_id"] = self.settings_vars["telegram_channel_id"].get()

        cfg["openai_api_key"] = self.settings_vars["openai_api_key"].get()
        cfg["openai_base_url"] = self.settings_vars["openai_base_url"].get()
        cfg["openai_model"] = self.settings_vars["openai_model"].get()

        cfg["check_interval_minutes"] = int(self.settings_vars["check_interval_minutes"].get())
        cfg["daily_summary_hour"] = int(self.settings_vars["daily_summary_hour"].get())
        cfg["daily_summary_minute"] = int(self.settings_vars["daily_summary_minute"].get())
        cfg["min_message_length"] = int(self.settings_vars["min_message_length"].get())
        cfg["similarity_threshold"] = float(self.settings_vars["similarity_threshold"].get())
        cfg["max_retries"] = int(self.settings_vars["max_retries"].get())
        cfg["request_timeout_seconds"] = int(self.settings_vars["request_timeout_seconds"].get())
        cfg["max_images_per_post"] = int(self.settings_vars["max_images_per_post"].get())

        cfg["publish_high_priority"] = self.settings_vars["publish_high_priority"].get()
        cfg["publish_medium_priority"] = self.settings_vars["publish_medium_priority"].get()
        cfg["publish_low_priority"] = self.settings_vars["publish_low_priority"].get()

        cfg["database_path"] = self.settings_vars["database_path"].get()
        cfg["log_file"] = self.settings_vars["log_file"].get()

        # Discord source
        if "sources" not in cfg:
            cfg["sources"] = {}
        if "discord" not in cfg["sources"]:
            cfg["sources"]["discord"] = {}
        cfg["sources"]["discord"]["guild_id"] = self.settings_vars["discord_guild_id"].get()
        cfg["sources"]["discord"]["channel_id"] = self.settings_vars["discord_channel_id"].get()

        # Пишем
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        print(f"[GUI] Конфиг сохранён: {self.config_path}")
        self.append_log("INFO", "Конфигурация сохранена")

        # Если бот запущен — перезагружаем конфиг
        if self.bot_instance:
            try:
                self.bot_instance.config = cfg
                self.append_log("INFO", "Конфигурация перезагружена в боте")
            except Exception as e:
                self.append_log("ERROR", f"Ошибка перезагрузки конфига: {e}")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Строит весь интерфейс."""

        # === Заголовок ===
        header = ctk.CTkFrame(self.root, fg_color=("#1a1a2e", "#1a1a2e"), height=50)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        title_label = ctk.CTkLabel(
            header,
            text="DayZ News Monitor",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#e94560",
        )
        title_label.pack(side="left", padx=15, pady=10)

        self.status_label = ctk.CTkLabel(
            header,
            text="Ожидание...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#a8a8a8",
        )
        self.status_label.pack(side="right", padx=15, pady=10)

        self.uptime_label = ctk.CTkLabel(
            header,
            text="00:00:00",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="#a8a8a8",
        )
        self.uptime_label.pack(side="right", padx=5, pady=10)

        # === Tabview ===
        self.tabview = ctk.CTkTabview(self.root, anchor="nw")
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_dashboard = self.tabview.add("Dashboard")
        self.tab_settings = self.tabview.add("Settings")
        self.tab_logs = self.tabview.add("Logs")

        self._build_dashboard()
        self._build_settings()
        self._build_logs()

    def _build_dashboard(self):
        """Вкладка Dashboard — статусы и счётчики."""
        frame = ctk.CTkScrollableFrame(self.tab_dashboard, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        # --- Статусы компонентов ---
        status_section = ctk.CTkFrame(frame, fg_color=("#16213e", "#16213e"), corner_radius=10)
        status_section.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            status_section,
            text="Статус компонентов",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#e94560",
        ).pack(anchor="w", padx=15, pady=(10, 5))

        self.status_cards = {}
        components = [
            ("discord", "Discord Monitor", "Disconnected"),
            ("ai", "AI Analyzer", "Disconnected"),
            ("telegram", "Telegram Publisher", "Disconnected"),
            ("scheduler", "Scheduler", "Disconnected"),
            ("database", "Database", "Disconnected"),
        ]

        for key, name, default_status in components:
            card = ctk.CTkFrame(status_section, fg_color=("#0f3460", "#0f3460"), corner_radius=8)
            card.pack(fill="x", padx=15, pady=3)

            name_label = ctk.CTkLabel(
                card, text=name, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
            )
            name_label.pack(side="left", padx=10, pady=8)

            status_indicator = ctk.CTkLabel(
                card, text=default_status,
                font=ctk.CTkFont(family="Consolas", size=11),
                text_color="#ff6b6b",
            )
            status_indicator.pack(side="right", padx=10, pady=8)

            self.status_cards[key] = status_indicator

        # --- Счётчики ---
        counters_section = ctk.CTkFrame(frame, fg_color=("#16213e", "#16213e"), corner_radius=10)
        counters_section.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(
            counters_section,
            text="Статистика",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#e94560",
        ).pack(anchor="w", padx=15, pady=(10, 5))

        self.counter_labels = {}
        counters = [
            ("messages_total", "Всего сообщений", "0"),
            ("messages_analyzed", "Проанализировано", "0"),
            ("messages_published", "Опубликовано", "0"),
            ("messages_duplicates", "Дубликатов", "0"),
        ]

        for key, name, default_val in counters:
            row = ctk.CTkFrame(counters_section, fg_color=("#0f3460", "#0f3460"), corner_radius=8)
            row.pack(fill="x", padx=15, pady=3)

            ctk.CTkLabel(
                row, text=name,
                font=ctk.CTkFont(family="Segoe UI", size=12),
            ).pack(side="left", padx=10, pady=8)

            val_label = ctk.CTkLabel(
                row, text=default_val,
                font=ctk.CTkFont(family="Consolas", size=14, weight="bold"),
                text_color="#00d2ff",
            )
            val_label.pack(side="right", padx=10, pady=8)

            self.counter_labels[key] = val_label

    def _build_settings(self):
        """Вкладка Settings — все настройки из config.json."""
        scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        self.settings_vars = {}

        # --- Discord ---
        self._section_label(scroll, "Discord")
        self.settings_vars["discord_token"] = self._add_entry(
            scroll, "User Token:", self.config.get("discord_token", ""), show="*"
        )
        self.settings_vars["discord_guild_id"] = self._add_entry(
            scroll, "Guild ID:", self.config.get("sources", {}).get("discord", {}).get("guild_id", "")
        )
        self.settings_vars["discord_channel_id"] = self._add_entry(
            scroll, "Channel ID:", self.config.get("sources", {}).get("discord", {}).get("channel_id", "")
        )

        # --- Telegram ---
        self._section_label(scroll, "Telegram")
        self.settings_vars["telegram_bot_token"] = self._add_entry(
            scroll, "Bot Token:", self.config.get("telegram_bot_token", ""), show="*"
        )
        self.settings_vars["telegram_channel_id"] = self._add_entry(
            scroll, "Channel ID:", self.config.get("telegram_channel_id", "")
        )

        # --- AI ---
        self._section_label(scroll, "AI (NVIDIA/OpenAI)")
        self.settings_vars["openai_api_key"] = self._add_entry(
            scroll, "API Key:", self.config.get("openai_api_key", ""), show="*"
        )
        self.settings_vars["openai_base_url"] = self._add_entry(
            scroll, "Base URL:", self.config.get("openai_base_url", "https://api.openai.com/v1")
        )
        self.settings_vars["openai_model"] = self._add_entry(
            scroll, "Model:", self.config.get("openai_model", "gpt-4o-mini")
        )

        # --- VK ---
        self._section_label(scroll, "VK")
        self.settings_vars["vk_access_token"] = self._add_entry(
            scroll, "Access Token:", self.config.get("vk_access_token", ""), show="*"
        )
        self.settings_vars["vk_api_version"] = self._add_entry(
            scroll, "API Version:", self.config.get("vk_api_version", "5.199")
        )

        # --- Параметры ---
        self._section_label(scroll, "Parameters")
        self.settings_vars["check_interval_minutes"] = self._add_entry(
            scroll, "Check Interval (min):", str(self.config.get("check_interval_minutes", 5))
        )
        self.settings_vars["daily_summary_hour"] = self._add_entry(
            scroll, "Summary Hour (UTC):", str(self.config.get("daily_summary_hour", 10))
        )
        self.settings_vars["daily_summary_minute"] = self._add_entry(
            scroll, "Summary Minute:", str(self.config.get("daily_summary_minute", 0))
        )
        self.settings_vars["min_message_length"] = self._add_entry(
            scroll, "Min Message Length:", str(self.config.get("min_message_length", 20))
        )
        self.settings_vars["similarity_threshold"] = self._add_entry(
            scroll, "Similarity Threshold:", str(self.config.get("similarity_threshold", 0.85))
        )
        self.settings_vars["max_retries"] = self._add_entry(
            scroll, "Max Retries:", str(self.config.get("max_retries", 3))
        )
        self.settings_vars["request_timeout_seconds"] = self._add_entry(
            scroll, "Request Timeout (sec):", str(self.config.get("request_timeout_seconds", 30))
        )
        self.settings_vars["max_images_per_post"] = self._add_entry(
            scroll, "Max Images Per Post:", str(self.config.get("max_images_per_post", 10))
        )
        self.settings_vars["database_path"] = self._add_entry(
            scroll, "Database Path:", self.config.get("database_path", "database/dayz_news.db")
        )
        self.settings_vars["log_file"] = self._add_entry(
            scroll, "Log File:", self.config.get("log_file", "logs/app.log")
        )

        # --- Приоритеты ---
        self._section_label(scroll, "Priority Filters")
        self.settings_vars["publish_high_priority"] = self._add_checkbox(
            scroll, "Публиковать High Priority",
            self.config.get("publish_high_priority", True)
        )
        self.settings_vars["publish_medium_priority"] = self._add_checkbox(
            scroll, "Публиковать Medium Priority",
            self.config.get("publish_medium_priority", True)
        )
        self.settings_vars["publish_low_priority"] = self._add_checkbox(
            scroll, "Публиковать Low Priority",
            self.config.get("publish_low_priority", False)
        )

        # --- Кнопки ---
        btn_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)

        save_btn = ctk.CTkButton(
            btn_frame, text="Save Configuration",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=("#e94560", "#e94560"),
            hover_color=("#c73e54", "#c73e54"),
            height=40,
            command=self._save_config,
        )
        save_btn.pack(fill="x", pady=(0, 5))

        reload_btn = ctk.CTkButton(
            btn_frame, text="Reload from File",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=("#0f3460", "#0f3460"),
            hover_color=("#16213e", "#16213e"),
            height=35,
            command=self._reload_config,
        )
        reload_btn.pack(fill="x")

    def _build_logs(self):
        """Вкладка Logs — лог в реальном времени."""
        # Фильтры
        filter_frame = ctk.CTkFrame(self.tab_logs, fg_color=("#16213e", "#16213e"), corner_radius=8)
        filter_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(
            filter_frame, text="Level Filter:",
            font=ctk.CTkFont(family="Segoe UI", size=11),
        ).pack(side="left", padx=10, pady=5)

        self.log_level_var = tk.StringVar(value="ALL")
        for level in ["ALL", "INFO", "WARNING", "ERROR"]:
            ctk.CTkRadioButton(
                filter_frame, text=level, variable=self.log_level_var, value=level,
                font=ctk.CTkFont(family="Segoe UI", size=11),
            ).pack(side="left", padx=5, pady=5)

        clear_btn = ctk.CTkButton(
            filter_frame, text="Clear", width=60, height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("#e94560", "#e94560"),
            command=self._clear_logs,
        )
        clear_btn.pack(side="right", padx=10, pady=5)

        # Текст логов
        self.log_text = ctk.CTkTextbox(
            self.tab_logs,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=("#0a0a0a", "#0a0a0a"),
            text_color="#a8a8a8",
            state="disabled",
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(5, 10))

    # ------------------------------------------------------------------
    # UI хелперы
    # ------------------------------------------------------------------

    def _section_label(self, parent, text):
        frame = ctk.CTkFrame(parent, fg_color=("#16213e", "#16213e"), corner_radius=8)
        frame.pack(fill="x", padx=10, pady=(12, 3))
        ctk.CTkLabel(
            frame, text=text,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#e94560",
        ).pack(anchor="w", padx=15, pady=6)

    def _add_entry(self, parent, label_text, default_value, show=None):
        row = ctk.CTkFrame(parent, fg_color=("transparent", "transparent"))
        row.pack(fill="x", padx=15, pady=2)

        lbl = ctk.CTkLabel(
            row, text=label_text,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            width=180,
            anchor="w",
        )
        lbl.pack(side="left", padx=(0, 10))

        entry = ctk.CTkEntry(
            row, width=400, height=30,
            font=ctk.CTkFont(family="Consolas", size=11),
            show=show if show else None,
        )
        entry.pack(side="left", fill="x", expand=True)

        # Устанавливаем значение ПОСЛЕ создания виджета
        if default_value:
            entry.insert(0, str(default_value))

        # Привязываем к StringVar для удобного чтения/записи
        var = tk.StringVar(value=str(default_value) if default_value else "")
        entry.configure(textvariable=var)

        return var

    def _add_checkbox(self, parent, label_text, default_value):
        row = ctk.CTkFrame(parent, fg_color=("transparent", "transparent"))
        row.pack(fill="x", padx=15, pady=2)

        var = tk.BooleanVar(value=bool(default_value))

        cb = ctk.CTkCheckBox(
            row, text=label_text,
            variable=var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
        )
        cb.pack(side="left", padx=(0, 10))

        return var

    def _populate_settings_from_config(self):
        """Обновляет все поля настроек из загруженного конфига.
        Вызывается после _build_ui(), чтобы поля уже существовали.
        """
        if not self.config:
            print("[GUI] _populate_settings_from_config: self.config пустой!")
            return

        print(f"[GUI] _populate_settings_from_config: заполняю {len(self.settings_vars)} полей")

        mapping = {
            "discord_token": self.config.get("discord_token", ""),
            "discord_guild_id": self.config.get("sources", {}).get("discord", {}).get("guild_id", ""),
            "discord_channel_id": self.config.get("sources", {}).get("discord", {}).get("channel_id", ""),
            "telegram_bot_token": self.config.get("telegram_bot_token", ""),
            "telegram_channel_id": self.config.get("telegram_channel_id", ""),
            "openai_api_key": self.config.get("openai_api_key", ""),
            "openai_base_url": self.config.get("openai_base_url", ""),
            "openai_model": self.config.get("openai_model", ""),
            "vk_access_token": self.config.get("vk_access_token", ""),
            "vk_api_version": self.config.get("vk_api_version", ""),
            "check_interval_minutes": str(self.config.get("check_interval_minutes", 5)),
            "daily_summary_hour": str(self.config.get("daily_summary_hour", 10)),
            "daily_summary_minute": str(self.config.get("daily_summary_minute", 0)),
            "min_message_length": str(self.config.get("min_message_length", 20)),
            "similarity_threshold": str(self.config.get("similarity_threshold", 0.85)),
            "max_retries": str(self.config.get("max_retries", 3)),
            "request_timeout_seconds": str(self.config.get("request_timeout_seconds", 30)),
            "max_images_per_post": str(self.config.get("max_images_per_post", 10)),
            "database_path": self.config.get("database_path", ""),
            "log_file": self.config.get("log_file", ""),
        }

        for key, value in mapping.items():
            if key in self.settings_vars:
                try:
                    self.settings_vars[key].set(str(value) if value else "")
                except Exception:
                    pass

        # Boolean variables
        bool_mapping = {
            "publish_high_priority": self.config.get("publish_high_priority", True),
            "publish_medium_priority": self.config.get("publish_medium_priority", True),
            "publish_low_priority": self.config.get("publish_low_priority", False),
        }
        for key, value in bool_mapping.items():
            if key in self.settings_vars:
                try:
                    self.settings_vars[key].set(bool(value))
                except Exception:
                    pass

        print("[GUI] Настройки из config.json загружены в GUI")

    def _reload_config(self):
        """Перезагружает конфиг из файла и обновляет поля."""
        self._load_config()
        self._populate_settings_from_config()
        self.append_log("INFO", "Конфигурация перезагружена из файла")

    # ------------------------------------------------------------------
    # Логи
    # ------------------------------------------------------------------

    def append_log(self, level: str, message: str):
        """Добавляет сообщение в очередь логов (thread-safe)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] [{level}] {message}")

    def _poll_logs(self):
        """Фоновый поток — читает очередь и обновляет TextBox."""
        while self._log_poll_running:
            try:
                msg = self.log_queue.get(timeout=0.1)
                # Фильтрация по уровню
                selected_level = self.log_level_var.get()
                if selected_level != "ALL" and selected_level not in msg:
                    continue

                # Определяем цвет
                color = "#a8a8a8"  # default grey
                if "ERROR" in msg:
                    color = "#ff6b6b"
                elif "WARNING" in msg:
                    color = "#ffd93d"
                elif "INFO" in msg:
                    color = "#6bff6b"

                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n", color)
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
            except queue.Empty:
                continue
            except Exception:
                break

    def _clear_logs(self):
        """Очищает текст логов."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Обновление статусов
    # ------------------------------------------------------------------

    def update_status(self, component: str, status: str, connected: bool):
        """Обновляет статус компонента на Dashboard (thread-safe)."""
        color = "#6bff6b" if connected else "#ff6b6b"
        if component in self.status_cards:
            try:
                self.root.after(0, lambda c=component, s=status, col=color: self._safe_update_status(c, s, col))
            except Exception:
                pass

    def _safe_update_status(self, component, status, color):
        try:
            self.status_cards[component].configure(text=status, text_color=color)
        except Exception:
            pass

    def update_counter(self, key: str, value: int):
        """Обновляет счётчик на Dashboard (thread-safe)."""
        if key in self.counter_labels:
            try:
                self.root.after(0, lambda k=key, v=value: self._safe_update_counter(k, v))
            except Exception:
                pass

    def _safe_update_counter(self, key, value):
        try:
            self.counter_labels[key].configure(text=str(value))
        except Exception:
            pass

    def set_bot_status(self, text: str, color="#a8a8a8"):
        """Обновляет текст статуса в заголовке."""
        try:
            self.root.after(0, lambda: self.status_label.configure(text=text, text_color=color))
        except Exception:
            pass

    def update_uptime(self, seconds: int):
        """Обновляет uptime в заголовке."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        text = f"{h:02d}:{m:02d}:{s:02d}"
        try:
            self.root.after(0, lambda: self.uptime_label.configure(text=text))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Запуск / закрытие
    # ------------------------------------------------------------------

    def _on_close(self):
        """Обработчик закрытия окна."""
        print("[GUI] Закрытие окна...")
        self._log_poll_running = False
        self.root.destroy()

    def run(self):
        """Запускает GUI mainloop. Блокирует!"""
        print("[GUI] Запуск mainloop...")
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self._on_close()


# =============================================================================
# Для отладки — можно запустить GUI отдельно
# =============================================================================

if __name__ == "__main__":
    gui = DesktopGUI(config_path="config.json")
    gui.run()
