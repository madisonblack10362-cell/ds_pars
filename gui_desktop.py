"""
Desktop GUI for DayZ News Monitor.
Discord-style dark theme, proper column layout, real-time logs.
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path

import customtkinter as ctk


# Discord color scheme
BG_DARK      = "#1e1f22"
BG_PRIMARY   = "#2b2d31"
BG_SECONDARY = "#313338"
BG_TERTIARY  = "#383a40"
BG_INPUT     = "#383a40"
BG_HOVER     = "#35373c"
TEXT_NORMAL  = "#dbdee1"
TEXT_MUTED   = "#949ba4"
TEXT_HEADER  = "#f2f3f5"
ACCENT       = "#5865f2"
ACCENT_HOVER = "#4752c4"
GREEN        = "#57f287"
YELLOW       = "#fee75c"
RED          = "#ed4245"
BORDER       = "#3f4147"


class DesktopGUI:
    def __init__(self, config_path="config.json", bot_instance=None):
        self.config_path = config_path
        self.bot_instance = bot_instance
        self.config = {}
        self.log_queue = queue.Queue()

        # Theme
        ctk.set_appearance_mode("dark")

        # Window
        self.root = ctk.CTk()
        self.root.title("DayZ News Monitor")
        self.root.geometry("960x680")
        self.root.minsize(860, 600)
        self.root.configure(fg_color=BG_DARK)

        # Load config
        self._load_config()

        # Build UI
        self._build_ui()

        # Fill fields from config
        self._populate_settings()

        # Log poller
        self._poll_running = True
        threading.Thread(target=self._poll_logs, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================================================================
    # Config
    # ================================================================

    def _load_config(self):
        if self.bot_instance and hasattr(self.bot_instance, 'config') and self.bot_instance.config:
            self.config = dict(self.bot_instance.config)
            return

        p = Path(self.config_path).resolve()
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception:
                self.config = {}

    def _save_config(self):
        p = Path(self.config_path)
        cfg = {}
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass

        # String fields
        str_keys = {
            "discord_token": None, "telegram_bot_token": None,
            "telegram_channel_id": None, "openai_api_key": None,
            "openai_base_url": None, "openai_model": None,
            "vk_access_token": None, "vk_api_version": None,
            "database_path": None, "log_file": None,
        }
        for key in str_keys:
            if key in self.vars:
                cfg[key] = self.vars[key].get()

        # Int fields
        int_keys = {
            "check_interval_minutes": 5, "daily_summary_hour": 10,
            "daily_summary_minute": 0, "min_message_length": 20,
            "max_retries": 3, "request_timeout_seconds": 30,
            "max_images_per_post": 10,
        }
        for key, default in int_keys.items():
            if key in self.vars:
                try:
                    cfg[key] = int(self.vars[key].get())
                except ValueError:
                    cfg[key] = default

        # Float fields
        if "similarity_threshold" in self.vars:
            try:
                cfg["similarity_threshold"] = float(self.vars["similarity_threshold"].get())
            except ValueError:
                cfg["similarity_threshold"] = 0.85

        # Boolean fields
        for key in ("publish_high_priority", "publish_medium_priority", "publish_low_priority"):
            if key in self.vars:
                cfg[key] = self.vars[key].get()

        # Discord sources
        if "sources" not in cfg:
            cfg["sources"] = {}
        if "discord" not in cfg["sources"]:
            cfg["sources"]["discord"] = {}
        if "discord_guild_id" in self.vars:
            cfg["sources"]["discord"]["guild_id"] = self.vars["discord_guild_id"].get()
        if "discord_channel_id" in self.vars:
            cfg["sources"]["discord"]["channel_id"] = self.vars["discord_channel_id"].get()

        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        self.append_log("INFO", "Configuration saved to config.json")

        if self.bot_instance:
            try:
                self.bot_instance.config = cfg
            except Exception:
                pass

    # ================================================================
    # UI Layout
    # ================================================================

    def _build_ui(self):
        # Header bar
        header = tk.Frame(self.root, bg=BG_PRIMARY, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="  DayZ News Monitor",
            bg=BG_PRIMARY, fg=ACCENT,
            font=("Segoe UI", 14, "bold"), anchor="w"
        ).pack(side="left", padx=8)

        self.uptime_var = tk.StringVar(value="00:00:00")
        tk.Label(
            header, textvariable=self.uptime_var,
            bg=BG_PRIMARY, fg=TEXT_MUTED,
            font=("Consolas", 10)
        ).pack(side="right", padx=16)

        self.status_var = tk.StringVar(value="Waiting...")
        tk.Label(
            header, textvariable=self.status_var,
            bg=BG_PRIMARY, fg=TEXT_MUTED,
            font=("Segoe UI", 10)
        ).pack(side="right", padx=8)

        # Tab bar
        tab_bar = tk.Frame(self.root, bg=BG_PRIMARY, height=40)
        tab_bar.pack(fill="x", padx=12, pady=(8, 0))

        self.tab_buttons = []
        tab_names = ["Dashboard", "Settings", "Logs"]

        for i, name in enumerate(tab_names):
            btn = tk.Frame(tab_bar, bg=BG_TERTIARY if i == 0 else BG_PRIMARY, cursor="hand2")
            btn.pack(side="left", padx=(0, 2))
            btn.pack_propagate(False)

            lbl = tk.Label(
                btn, text=f"  {name}  ", bg=btn["bg"], fg=TEXT_HEADER if i == 0 else TEXT_MUTED,
                font=("Segoe UI", 10, "bold" if i == 0 else "normal"), cursor="hand2",
                padx=12, pady=8,
            )
            lbl.pack(fill="both", expand=True)

            btn.bind("<Button-1>", lambda e, idx=i, b=btn, l=lbl: self._switch_tab(idx, b, l))
            lbl.bind("<Button-1>", lambda e, idx=i, b=btn, l=lbl: self._switch_tab(idx, b, l))
            self.tab_buttons.append((btn, lbl))

        # Tab frames
        self.tab_container = tk.Frame(self.root, bg=BG_DARK)
        self.tab_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.tab_frames = []
        for name in tab_names:
            frame = tk.Frame(self.tab_container, bg=BG_DARK)
            self.tab_frames.append(frame)

        self._build_dashboard(self.tab_frames[0])
        self._build_settings(self.tab_frames[1])
        self._build_logs(self.tab_frames[2])

        # Show first tab
        self.tab_frames[0].pack(fill="both", expand=True)

    # ----------------------------------------------------------------
    # Dashboard
    # ----------------------------------------------------------------

    def _build_dashboard(self, parent):
        parent.configure(fg_color=BG_DARK)

        # Status section
        sec = tk.LabelFrame(
            parent, text=" Components ", bg=BG_PRIMARY, fg=ACCENT,
            font=("Segoe UI", 11, "bold"), bd=1, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
        )
        sec.pack(fill="x", padx=8, pady=(8, 4))

        self.status_cards = {}
        items = [
            ("Discord", "Disconnected", RED),
            ("AI Analyzer", "Disconnected", RED),
            ("Telegram", "Disconnected", RED),
            ("Scheduler", "Disconnected", RED),
            ("Database", "Disconnected", RED),
        ]
        for name, status, color in items:
            row = tk.Frame(sec, bg=BG_SECONDARY, height=36)
            row.pack(fill="x", padx=6, pady=2)
            row.pack_propagate(False)

            tk.Label(
                row, text=f"  {name}", bg=BG_SECONDARY, fg=TEXT_HEADER,
                font=("Segoe UI", 10, "bold"), anchor="w"
            ).pack(side="left", padx=8)

            lbl = tk.Label(
                row, text=status, bg=BG_SECONDARY, fg=color,
                font=("Consolas", 10), anchor="e"
            )
            lbl.pack(side="right", padx=12)
            self.status_cards[name.lower().split()[0]] = lbl

        # Stats section
        sec2 = tk.LabelFrame(
            parent, text=" Statistics ", bg=BG_PRIMARY, fg=ACCENT,
            font=("Segoe UI", 11, "bold"), bd=1, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
        )
        sec2.pack(fill="x", padx=8, pady=4)

        self.counter_vars = {}
        counters = [
            ("total", "Messages Collected"),
            ("analyzed", "Analyzed"),
            ("published", "Published"),
            ("duplicates", "Duplicates"),
        ]
        for key, label in counters:
            row = tk.Frame(sec2, bg=BG_SECONDARY, height=36)
            row.pack(fill="x", padx=6, pady=2)
            row.pack_propagate(False)

            tk.Label(
                row, text=f"  {label}", bg=BG_SECONDARY, fg=TEXT_NORMAL,
                font=("Segoe UI", 10), anchor="w"
            ).pack(side="left", padx=8)

            var = tk.StringVar(value="0")
            tk.Label(
                row, textvariable=var, bg=BG_SECONDARY, fg=GREEN,
                font=("Consolas", 12, "bold"), anchor="e"
            ).pack(side="right", padx=12)
            self.counter_vars[key] = var

    # ----------------------------------------------------------------
    # Settings — Discord-style columns
    # ----------------------------------------------------------------

    def _build_settings(self, parent):
        parent.configure(fg_color=BG_DARK)

        self.vars = {}

        # Scrollable canvas
        canvas = tk.Canvas(parent, bg=BG_DARK, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG_DARK)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", padx=(0, 8), pady=8)

        # Mousewheel scroll
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # --- Build sections ---
        sections = [
            ("DISCORD", [
                ("discord_token", "User Token", True),
                ("discord_guild_id", "Guild ID", False),
                ("discord_channel_id", "Channel ID", False),
            ]),
            ("TELEGRAM", [
                ("telegram_bot_token", "Bot Token", True),
                ("telegram_channel_id", "Channel ID", False),
            ]),
            ("AI / NVIDIA", [
                ("openai_api_key", "API Key", True),
                ("openai_base_url", "Base URL", False),
                ("openai_model", "Model", False),
            ]),
            ("VK", [
                ("vk_access_token", "Access Token", True),
                ("vk_api_version", "API Version", False),
            ]),
            ("PARAMETERS", [
                ("check_interval_minutes", "Check Interval (min)", False),
                ("daily_summary_hour", "Summary Hour (UTC)", False),
                ("daily_summary_minute", "Summary Minute", False),
                ("min_message_length", "Min Message Length", False),
                ("similarity_threshold", "Similarity Threshold", False),
                ("max_retries", "Max Retries", False),
                ("request_timeout_seconds", "Request Timeout (sec)", False),
                ("max_images_per_post", "Max Images Per Post", False),
                ("database_path", "Database Path", False),
                ("log_file", "Log File", False),
            ]),
            ("PRIORITY FILTERS", [
                ("publish_high_priority", "High Priority", None),
                ("publish_medium_priority", "Medium Priority", None),
                ("publish_low_priority", "Low Priority", None),
            ]),
        ]

        for section_title, fields in sections:
            # Section header
            hdr = tk.Frame(scroll_frame, bg=BG_PRIMARY, height=32)
            hdr.pack(fill="x", padx=4, pady=(10, 0))
            hdr.pack_propagate(False)

            tk.Label(
                hdr, text=f"  {section_title}",
                bg=BG_PRIMARY, fg=ACCENT,
                font=("Segoe UI", 10, "bold"), anchor="w"
            ).pack(side="left", padx=4)

            # Fields container
            box = tk.Frame(scroll_frame, bg=BG_SECONDARY, bd=0)
            box.pack(fill="x", padx=4, pady=(2, 0))

            for i, (key, label, is_secret) in enumerate(fields):
                self._add_field(box, key, label, is_secret, i % 2 == 0)

        # --- Buttons ---
        btn_box = tk.Frame(scroll_frame, bg=BG_DARK)
        btn_box.pack(fill="x", padx=4, pady=12)

        # Save button
        save_frame = tk.Frame(btn_box, bg=ACCENT, height=36, cursor="hand2")
        save_frame.pack(fill="x", pady=(0, 4))
        save_frame.pack_propagate(False)
        save_frame.bind("<Button-1>", lambda e: self._save_config())

        tk.Label(
            save_frame, text="  Save Configuration",
            bg=ACCENT, fg=TEXT_HEADER,
            font=("Segoe UI", 11, "bold"), anchor="w", cursor="hand2"
        ).pack(side="left", padx=8, fill="y", expand=True)

        # Reload button
        reload_frame = tk.Frame(btn_box, bg=BG_TERTIARY, height=32, cursor="hand2")
        reload_frame.pack(fill="x")
        reload_frame.pack_propagate(False)
        reload_frame.bind("<Button-1>", lambda e: self._reload_config())

        tk.Label(
            reload_frame, text="  Reload from File",
            bg=BG_TERTIARY, fg=TEXT_MUTED,
            font=("Segoe UI", 10), anchor="w", cursor="hand2"
        ).pack(side="left", padx=8, fill="y", expand=True)

    def _add_field(self, parent, key, label, is_secret, alt_row):
        bg = BG_SECONDARY if not alt_row else BG_TERTIARY

        row = tk.Frame(parent, bg=bg, height=34)
        row.pack(fill="x")
        row.pack_propagate(False)

        tk.Label(
            row, text=f"  {label}", bg=bg, fg=TEXT_NORMAL,
            font=("Segoe UI", 10), width=24, anchor="w"
        ).pack(side="left", padx=(8, 4))

        if is_secret is None:
            # Checkbox
            var = tk.BooleanVar(value=False)
            self.vars[key] = var
            cb = tk.Checkbutton(
                row, variable=var, bg=bg, fg=TEXT_NORMAL,
                selectcolor=BG_INPUT, activebackground=bg,
                activeforeground=TEXT_NORMAL,
                font=("Segoe UI", 10), cursor="hand2",
            )
            cb.pack(side="left", padx=8)
        else:
            # Entry
            var = tk.StringVar(value="")
            self.vars[key] = var

            entry = tk.Entry(
                row, textvariable=var,
                bg=BG_INPUT, fg=TEXT_HEADER,
                insertbackground=TEXT_HEADER,
                font=("Consolas", 10),
                relief="flat", bd=4, cursor="xterm",
                show="*" if is_secret else "",
            )
            entry.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=6)

    # ----------------------------------------------------------------
    # Logs
    # ----------------------------------------------------------------

    def _build_logs(self, parent):
        parent.configure(fg_color=BG_DARK)

        # Filter bar
        bar = tk.Frame(parent, bg=BG_PRIMARY, height=38)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        bar.pack_propagate(False)

        tk.Label(
            bar, text="  Filter:", bg=BG_PRIMARY, fg=TEXT_MUTED,
            font=("Segoe UI", 10)
        ).pack(side="left", padx=4)

        self.log_level_var = tk.StringVar(value="ALL")
        for level in ("ALL", "INFO", "WARNING", "ERROR"):
            tk.Radiobutton(
                bar, text=level, variable=self.log_level_var, value=level,
                bg=BG_PRIMARY, fg=TEXT_MUTED, selectcolor=BG_TERTIARY,
                activebackground=BG_PRIMARY, activeforeground=TEXT_HEADER,
                font=("Segoe UI", 10), indicatoron=0, padx=10, pady=4,
                cursor="hand2",
            ).pack(side="left", padx=2)

        # Clear button
        clear = tk.Frame(bar, bg=RED, cursor="hand2", height=24, width=50)
        clear.pack(side="right", padx=8, pady=6)
        clear.pack_propagate(False)
        clear.bind("<Button-1>", lambda e: self._clear_logs())
        tk.Label(
            clear, text="Clear", bg=RED, fg=TEXT_HEADER,
            font=("Segoe UI", 9, "bold"), cursor="hand2"
        ).pack(fill="both", expand=True)

        # Log text
        self.log_text = tk.Text(
            parent, bg=BG_PRIMARY, fg=TEXT_NORMAL,
            font=("Consolas", 10), relief="flat", bd=0,
            insertbackground=TEXT_HEADER, wrap="word",
            state="disabled", padx=10, pady=8,
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Configure tags
        self.log_text.tag_configure("info", foreground=GREEN)
        self.log_text.tag_configure("warning", foreground=YELLOW)
        self.log_text.tag_configure("error", foreground=RED)
        self.log_text.tag_configure("default", foreground=TEXT_MUTED)

    def _switch_tab(self, idx, btn, lbl):
        for frame in self.tab_frames:
            frame.pack_forget()
        for i, (b, l) in enumerate(self.tab_buttons):
            b.configure(bg=BG_TERTIARY if i == idx else BG_PRIMARY)
            l.configure(bg=BG_TERTIARY if i == idx else BG_PRIMARY,
                        fg=TEXT_HEADER if i == idx else TEXT_MUTED,
                        font=("Segoe UI", 10, "bold" if i == idx else "normal"))
        self.tab_frames[idx].pack(fill="both", expand=True)

    # ================================================================
    # Populate / Reload
    # ================================================================

    def _populate_settings(self):
        if not self.config:
            return

        str_map = {
            "discord_token": self.config.get("discord_token", ""),
            "telegram_bot_token": self.config.get("telegram_bot_token", ""),
            "telegram_channel_id": self.config.get("telegram_channel_id", ""),
            "openai_api_key": self.config.get("openai_api_key", ""),
            "openai_base_url": self.config.get("openai_base_url", ""),
            "openai_model": self.config.get("openai_model", ""),
            "vk_access_token": self.config.get("vk_access_token", ""),
            "vk_api_version": self.config.get("vk_api_version", ""),
            "database_path": self.config.get("database_path", ""),
            "log_file": self.config.get("log_file", ""),
            "discord_guild_id": self.config.get("sources", {}).get("discord", {}).get("guild_id", ""),
            "discord_channel_id": self.config.get("sources", {}).get("discord", {}).get("channel_id", ""),
        }
        for key, val in str_map.items():
            if key in self.vars and val:
                self.vars[key].set(str(val))

        num_map = {
            "check_interval_minutes": self.config.get("check_interval_minutes", 5),
            "daily_summary_hour": self.config.get("daily_summary_hour", 10),
            "daily_summary_minute": self.config.get("daily_summary_minute", 0),
            "min_message_length": self.config.get("min_message_length", 20),
            "similarity_threshold": self.config.get("similarity_threshold", 0.85),
            "max_retries": self.config.get("max_retries", 3),
            "request_timeout_seconds": self.config.get("request_timeout_seconds", 30),
            "max_images_per_post": self.config.get("max_images_per_post", 10),
        }
        for key, val in num_map.items():
            if key in self.vars:
                self.vars[key].set(str(val))

        bool_map = {
            "publish_high_priority": self.config.get("publish_high_priority", True),
            "publish_medium_priority": self.config.get("publish_medium_priority", True),
            "publish_low_priority": self.config.get("publish_low_priority", False),
        }
        for key, val in bool_map.items():
            if key in self.vars:
                self.vars[key].set(bool(val))

    def _reload_config(self):
        self._load_config()
        self._populate_settings()
        self.append_log("INFO", "Configuration reloaded from file")

    # ================================================================
    # Logs
    # ================================================================

    def append_log(self, level, message):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] [{level}] {message}")

    def _poll_logs(self):
        while self._poll_running:
            try:
                msg = self.log_queue.get(timeout=0.1)
                level_filter = self.log_level_var.get()
                if level_filter != "ALL":
                    if level_filter not in msg:
                        continue

                if "ERROR" in msg or "CRITICAL" in msg:
                    tag = "error"
                elif "WARNING" in msg:
                    tag = "warning"
                elif "INFO" in msg:
                    tag = "info"
                else:
                    tag = "default"

                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n", tag)
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
            except queue.Empty:
                continue
            except Exception:
                break

    def _clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ================================================================
    # Status / Counter updates (thread-safe)
    # ================================================================

    def update_status(self, component, text, color):
        mapping = {
            "discord": "discord", "ai": "ai", "telegram": "telegram",
            "scheduler": "scheduler", "database": "database",
        }
        key = mapping.get(component, component)
        if key in self.status_cards:
            try:
                self.root.after(0, lambda: self.status_cards[key].configure(
                    text=text, fg=color
                ))
            except Exception:
                pass

    def update_counter(self, key, value):
        if key in self.counter_vars:
            try:
                self.root.after(0, lambda: self.counter_vars[key].set(str(value)))
            except Exception:
                pass

    def set_bot_status(self, text, color=TEXT_MUTED):
        try:
            self.root.after(0, lambda: self.status_var.set(text))
        except Exception:
            pass

    def update_uptime(self, seconds):
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        try:
            self.root.after(0, lambda: self.uptime_var.set(f"{h:02d}:{m:02d}:{s:02d}"))
        except Exception:
            pass

    # ================================================================
    # Run / Close
    # ================================================================

    def _on_close(self):
        self._poll_running = False
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    gui = DesktopGUI(config_path="config.json")
    gui.run()
