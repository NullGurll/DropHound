from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import psutil
from PIL import Image

from cyberdrop_desk import __version__
from cyberdrop_desk.core import (
    ENGINE_VERSION,
    HistoryEntry,
    HistoryStore,
    Settings,
    app_data_dir,
    clean_output,
    download_command,
    normalize_urls,
    parse_file_progress,
    parse_supported_sites,
    process_startup_kwargs,
    retry_failed_command,
    supported_sites_command,
    utc_now,
    write_engine_config,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#0A0F1C"
SURFACE = "#111827"
SURFACE_2 = "#172033"
BORDER = "#243047"
TEXT = "#F8FAFC"
MUTED = "#94A3B8"
ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
SUCCESS = "#22C55E"
DANGER = "#EF4444"
DISK = "#34D399"
URLS_EXAMPLE = "Paste one link per line, for example:\nhttps://example.com/album-one\nhttps://example.com/album-two"


def bundled_asset(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "assets" / name


def format_bytes(value: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = max(0.0, value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


def format_speed(value: float) -> str:
    return f"{format_bytes(value)}/s"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def folder_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


class TransferGraph(tk.Canvas):
    def __init__(self, master: ctk.CTkFrame) -> None:
        super().__init__(
            master,
            height=155,
            background="#080D18",
            highlightthickness=0,
            borderwidth=0,
        )
        self.download_values: deque[float] = deque([0.0] * 60, maxlen=60)
        self.disk_values: deque[float] = deque([0.0] * 60, maxlen=60)
        self.bind("<Configure>", lambda _event: self._draw())

    def push(self, download_speed: float, disk_speed: float) -> None:
        self.download_values.append(max(0.0, download_speed))
        self.disk_values.append(max(0.0, disk_speed))
        self._draw()

    def clear(self) -> None:
        self.download_values = deque([0.0] * 60, maxlen=60)
        self.disk_values = deque([0.0] * 60, maxlen=60)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        for ratio in (0.25, 0.5, 0.75):
            y = int(height * ratio)
            self.create_line(0, y, width, y, fill="#172033", width=1)
        maximum = max((*self.download_values, *self.disk_values, 1.0))
        points = len(self.download_values)
        step = width / max(points - 1, 1)
        bar_width = max(2, int(step * 0.58))
        for index, value in enumerate(self.download_values):
            x = index * step
            bar_height = (value / maximum) * (height - 10)
            self.create_rectangle(
                x - bar_width / 2,
                height - bar_height,
                x + bar_width / 2,
                height,
                fill=ACCENT,
                outline="",
            )
        disk_points: list[float] = []
        for index, value in enumerate(self.disk_values):
            disk_points.extend((index * step, height - (value / maximum) * (height - 10)))
        if len(disk_points) >= 4:
            self.create_line(*disk_points, fill=DISK, width=2, smooth=True)


class DropHound(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=BG)
        self.title(f"DropHound {__version__}")
        self.geometry("1100x760")
        self.minsize(920, 700)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.data_dir = app_data_dir()
        self.settings_path = self.data_dir / "settings.json"
        self.engine_config_path = self.data_dir / "engine-config.yaml"
        self.settings = Settings.load(self.settings_path)
        self.history = HistoryStore(self.data_dir / "history.json")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.started_at = ""
        self.active_url_count = 0
        self.cancel_requested = False
        self.telemetry_stop = threading.Event()
        self.telemetry_started = False
        self.transferred_bytes = 0
        self.peak_speed = 0.0
        self.file_progress_total = 0
        self.supported_sites_loaded = False
        self.urls_example_active = False

        self._build_shell()
        self._build_download_page()
        self._build_settings_page()
        self._build_history_page()
        self._build_about_page()
        self._load_settings_into_ui()
        self._show_page("download")
        self.after(100, self._poll_events)

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color="#0D1424")
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=24, pady=(28, 34))
        logo_image = Image.open(bundled_asset("drophound-icon.png"))
        self.brand_logo = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(44, 44))
        ctk.CTkLabel(
            brand,
            text="",
            image=self.brand_logo,
            width=44,
            height=44,
            fg_color="transparent",
        ).pack(side="left")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            brand_text,
            text="DropHound",
            text_color=TEXT,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text,
            text="PASTE. FETCH. DONE.",
            text_color=ACCENT,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label, symbol in (
            ("download", "Download", "↓"),
            ("settings", "Settings", "⚙"),
            ("history", "History", "◷"),
            ("about", "About & links", "ⓘ"),
        ):
            button = ctk.CTkButton(
                sidebar,
                text=f"  {symbol}   {label}",
                height=46,
                corner_radius=11,
                anchor="w",
                fg_color="transparent",
                hover_color=SURFACE_2,
                text_color=MUTED,
                font=ctk.CTkFont(size=14, weight="bold"),
                command=lambda page=key: self._show_page(page),
            )
            button.pack(fill="x", padx=16, pady=4)
            self.nav_buttons[key] = button

        version_card = ctk.CTkFrame(sidebar, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER)
        version_card.pack(side="bottom", fill="x", padx=16, pady=20)
        ctk.CTkLabel(
            version_card,
            text="DOWNLOADER CORE",
            text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            version_card,
            text=f"Cyberdrop-DL  {ENGINE_VERSION}",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=14)
        self.core_status = ctk.CTkLabel(
            version_card,
            text="●  Ready",
            text_color=SUCCESS,
            font=ctk.CTkFont(size=11),
        )
        self.core_status.pack(anchor="w", padx=14, pady=(4, 12))

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        for page in ("download", "settings", "history", "about"):
            frame = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            self.pages[page] = frame

    def _page_header(self, parent: ctk.CTkFrame, title: str, subtitle: str) -> None:
        ctk.CTkLabel(
            parent,
            text=title,
            text_color=TEXT,
            font=ctk.CTkFont(size=28, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=34, pady=(28, 2))
        ctk.CTkLabel(
            parent,
            text=subtitle,
            text_color=MUTED,
            font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, sticky="w", padx=34, pady=(0, 20))

    def _card(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        return ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)

    def _build_download_page(self) -> None:
        page = self.pages["download"]
        page.grid_rowconfigure(3, weight=1)
        self._page_header(page, "New download", "Paste links, choose where they go, and let the engine handle the rest.")

        input_card = self._card(page)
        input_card.grid(row=2, column=0, sticky="ew", padx=34)
        input_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            input_card,
            text="LINKS TO DOWNLOAD",
            text_color=MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 7))
        self.urls_text = ctk.CTkTextbox(
            input_card,
            height=118,
            corner_radius=11,
            fg_color="#0B1220",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(size=13),
        )
        self.urls_text.grid(row=1, column=0, sticky="ew", padx=18)
        self.urls_text.bind("<FocusIn>", self._clear_urls_example)
        self.urls_text.bind("<FocusOut>", self._restore_urls_example)
        self._show_urls_example()

        destination = ctk.CTkFrame(input_card, fg_color="transparent")
        destination.grid(row=2, column=0, sticky="ew", padx=18, pady=14)
        destination.grid_columnconfigure(0, weight=1)
        self.download_folder_var = ctk.StringVar()
        self.folder_entry = ctk.CTkEntry(
            destination,
            textvariable=self.download_folder_var,
            height=42,
            corner_radius=10,
            fg_color="#0B1220",
            border_color=BORDER,
            placeholder_text="Download destination",
        )
        self.folder_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            destination,
            text="Browse",
            width=86,
            height=42,
            corner_radius=10,
            fg_color=SURFACE_2,
            hover_color=BORDER,
            command=self._browse_download_folder,
        ).grid(row=0, column=1, padx=(10, 0))
        ctk.CTkButton(
            destination,
            text="Open",
            width=72,
            height=42,
            corner_radius=10,
            fg_color=SURFACE_2,
            hover_color=BORDER,
            command=self._open_download_folder,
        ).grid(row=0, column=2, padx=(8, 0))

        activity_card = self._card(page)
        activity_card.grid(row=3, column=0, sticky="nsew", padx=34, pady=16)
        activity_card.grid_columnconfigure(0, weight=1)
        activity_card.grid_rowconfigure(3, weight=1)
        activity_top = ctk.CTkFrame(activity_card, fg_color="transparent")
        activity_top.grid(row=0, column=0, sticky="ew", padx=18, pady=(15, 8))
        activity_top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            activity_top,
            text="ACTIVITY",
            text_color=MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        self.file_progress_label = ctk.CTkLabel(
            activity_top,
            text="FILES  —",
            text_color=TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.file_progress_label.grid(row=0, column=1)
        self.run_status = ctk.CTkLabel(
            activity_top,
            text="Ready for links",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        )
        self.run_status.grid(row=0, column=2, sticky="e")
        self.progress = ctk.CTkProgressBar(
            activity_card,
            height=5,
            corner_radius=3,
            fg_color="#1E293B",
            progress_color=ACCENT,
            mode="determinate",
        )
        self.progress.grid(row=1, column=0, sticky="ew", padx=18)
        self.progress.set(0)

        file_stats = ctk.CTkFrame(activity_card, fg_color="transparent")
        file_stats.grid(row=2, column=0, sticky="ew", padx=18, pady=(7, 0))
        for column in range(4):
            file_stats.grid_columnconfigure(column, weight=1)
        self.downloaded_files_value = self._file_stat(file_stats, 0, "DOWNLOADED", SUCCESS)
        self.queued_files_value = self._file_stat(file_stats, 1, "QUEUED", ACCENT)
        self.failed_files_value = self._file_stat(file_stats, 2, "FAILED", DANGER)
        self.skipped_files_value = self._file_stat(file_stats, 3, "SKIPPED", MUTED)

        dashboard = ctk.CTkFrame(activity_card, fg_color="transparent")
        dashboard.grid(row=3, column=0, sticky="nsew", padx=18, pady=(7, 5))
        dashboard.grid_columnconfigure(0, weight=1)
        dashboard.grid_columnconfigure(1, minsize=205)
        dashboard.grid_rowconfigure(0, weight=1)

        chart_card = ctk.CTkFrame(dashboard, fg_color="#080D18", corner_radius=10)
        chart_card.grid(row=0, column=0, sticky="nsew")
        chart_card.grid_columnconfigure(0, weight=1)
        chart_card.grid_rowconfigure(1, weight=1)
        legend = ctk.CTkFrame(chart_card, fg_color="transparent")
        legend.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            legend, text="■  NETWORK", text_color=ACCENT, font=ctk.CTkFont(size=10, weight="bold")
        ).pack(side="left")
        ctk.CTkLabel(
            legend, text="●  DISK ACTIVITY", text_color=DISK, font=ctk.CTkFont(size=10, weight="bold")
        ).pack(side="left", padx=(18, 0))
        self.transfer_graph = TransferGraph(chart_card)
        self.transfer_graph.grid(row=1, column=0, sticky="nsew", padx=6, pady=(3, 6))

        metrics = ctk.CTkFrame(dashboard, fg_color="#0D1525", corner_radius=10)
        metrics.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.current_speed_value = self._metric(metrics, "CURRENT", "0 B/s", ACCENT)
        self.peak_speed_value = self._metric(metrics, "PEAK", "0 B/s", TEXT)
        self.total_value = self._metric(metrics, "TRANSFERRED", "0 B", TEXT)
        self.disk_speed_value = self._metric(metrics, "DISK ACTIVITY", "0 B/s", DISK)
        self.elapsed_value = self._metric(metrics, "ELAPSED", "0:00", MUTED)

        self.log_text = ctk.CTkTextbox(
            activity_card,
            height=58,
            corner_radius=10,
            fg_color="#080D18",
            border_width=0,
            text_color="#CBD5E1",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_text.grid(row=4, column=0, sticky="ew", padx=18, pady=(5, 16))
        self.log_text.configure(state="disabled")

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=34, pady=(0, 24))
        actions.grid_columnconfigure(3, weight=1)
        self.download_button = ctk.CTkButton(
            actions,
            text="Start download",
            width=160,
            height=46,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_download,
        )
        self.download_button.grid(row=0, column=0)
        self.retry_button = ctk.CTkButton(
            actions,
            text="Retry failed",
            width=116,
            height=46,
            corner_radius=12,
            fg_color=SURFACE_2,
            hover_color=BORDER,
            command=self._retry_failed,
        )
        self.retry_button.grid(row=0, column=1, padx=9)
        self.cancel_button = ctk.CTkButton(
            actions,
            text="Cancel",
            width=92,
            height=46,
            corner_radius=12,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER,
            hover_color=SURFACE_2,
            state="disabled",
            command=self._cancel,
        )
        self.cancel_button.grid(row=0, column=2)
        ctk.CTkButton(
            actions,
            text="Clear links",
            width=96,
            height=40,
            corner_radius=10,
            fg_color="transparent",
            hover_color=SURFACE_2,
            text_color=MUTED,
            command=self._clear_urls,
        ).grid(row=0, column=4)

    def _metric(self, parent: ctk.CTkFrame, label: str, value: str, color: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=13, pady=(6, 0))
        ctk.CTkLabel(
            row, text=label, text_color=MUTED, font=ctk.CTkFont(size=9, weight="bold")
        ).pack(side="left")
        value_label = ctk.CTkLabel(
            row, text=value, text_color=color, font=ctk.CTkFont(size=12, weight="bold")
        )
        value_label.pack(side="right")
        return value_label

    def _file_stat(self, parent: ctk.CTkFrame, column: int, label: str, color: str) -> ctk.CTkLabel:
        box = ctk.CTkFrame(parent, fg_color="#0D1525", corner_radius=8)
        box.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4, 0))
        ctk.CTkLabel(
            box, text=label, text_color=MUTED, font=ctk.CTkFont(size=9, weight="bold")
        ).pack(side="left", padx=(10, 4), pady=5)
        value = ctk.CTkLabel(box, text="0", text_color=color, font=ctk.CTkFont(size=11, weight="bold"))
        value.pack(side="right", padx=(4, 10), pady=5)
        return value

    def _build_settings_page(self) -> None:
        page = self.pages["settings"]
        self._page_header(page, "Settings", "Choose what to download and how aggressively to run.")
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))
        page.grid_rowconfigure(2, weight=1)
        scroll.grid_columnconfigure((0, 1), weight=1)

        media = self._settings_card(scroll, "File types", "Only selected file types will be saved.", 0, 0)
        self.images_var = ctk.BooleanVar()
        self.videos_var = ctk.BooleanVar()
        self.audio_var = ctk.BooleanVar()
        self.other_var = ctk.BooleanVar()
        for label, variable in (
            ("Images", self.images_var),
            ("Videos", self.videos_var),
            ("Audio", self.audio_var),
            ("Archives and other files", self.other_var),
        ):
            ctk.CTkCheckBox(
                media,
                text=label,
                variable=variable,
                corner_radius=6,
                border_color=BORDER,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
            ).pack(anchor="w", padx=18, pady=7)

        behavior = self._settings_card(scroll, "Download behavior", "Advanced crawling and duplicate controls.", 0, 1)
        self.deep_scrape_var = ctk.BooleanVar()
        self.ignore_history_var = ctk.BooleanVar()
        ctk.CTkCheckBox(
            behavior,
            text="Deep scrape embedded links",
            variable=self.deep_scrape_var,
            corner_radius=6,
            border_color=BORDER,
        ).pack(anchor="w", padx=18, pady=8)
        ctk.CTkCheckBox(
            behavior,
            text="Allow duplicate downloads",
            variable=self.ignore_history_var,
            corner_radius=6,
            border_color=BORDER,
        ).pack(anchor="w", padx=18, pady=8)
        limits = ctk.CTkFrame(behavior, fg_color="transparent")
        limits.pack(fill="x", padx=18, pady=(12, 8))
        self.concurrent_var = ctk.IntVar()
        self.per_domain_var = ctk.IntVar()
        self._number_field(limits, "Total connections", self.concurrent_var).pack(side="left", fill="x", expand=True)
        self._number_field(limits, "Per website", self.per_domain_var).pack(
            side="left", fill="x", expand=True, padx=(10, 0)
        )

        cookies = self._settings_card(
            scroll, "Account cookies", "Optional Netscape cookies.txt for sites you can access.", 1, 0, span=2
        )
        cookie_row = ctk.CTkFrame(cookies, fg_color="transparent")
        cookie_row.pack(fill="x", padx=18, pady=(6, 16))
        self.cookies_var = ctk.StringVar()
        ctk.CTkEntry(
            cookie_row,
            textvariable=self.cookies_var,
            height=42,
            corner_radius=10,
            fg_color="#0B1220",
            border_color=BORDER,
            placeholder_text="No cookies file selected",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            cookie_row,
            text="Choose file",
            width=100,
            height=42,
            corner_radius=10,
            fg_color=SURFACE_2,
            hover_color=BORDER,
            command=self._browse_cookies,
        ).pack(side="left", padx=(10, 0))
        ctk.CTkButton(
            cookie_row,
            text="Clear",
            width=72,
            height=42,
            corner_radius=10,
            fg_color="transparent",
            hover_color=SURFACE_2,
            command=lambda: self.cookies_var.set(""),
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            scroll,
            text="Save settings",
            height=46,
            corner_radius=12,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._save_settings,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=12)

    def _settings_card(
        self,
        parent: ctk.CTkFrame,
        title: str,
        subtitle: str,
        row: int,
        column: int,
        span: int = 1,
    ) -> ctk.CTkFrame:
        card = self._card(parent)
        card.grid(row=row, column=column, columnspan=span, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(card, text=title, text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=18, pady=(16, 2)
        )
        ctk.CTkLabel(card, text=subtitle, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
            anchor="w", padx=18, pady=(0, 10)
        )
        return card

    def _number_field(self, parent: ctk.CTkFrame, label: str, variable: ctk.IntVar) -> ctk.CTkFrame:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(box, text=label, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")
        ctk.CTkEntry(
            box,
            textvariable=variable,
            height=38,
            corner_radius=9,
            fg_color="#0B1220",
            border_color=BORDER,
        ).pack(fill="x", pady=(4, 0))
        return box

    def _build_history_page(self) -> None:
        page = self.pages["history"]
        page.grid_rowconfigure(2, weight=1)
        self._page_header(page, "Download history", "Your latest runs and where their files were saved.")
        self.history_list = ctk.CTkScrollableFrame(
            page,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=BORDER,
        )
        self.history_list.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 24))

    def _build_about_page(self) -> None:
        page = self.pages["about"]
        page.grid_rowconfigure(2, weight=1)
        self._page_header(
            page,
            "About DropHound",
            "What it downloads, how it works, and which links are supported.",
        )
        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent", corner_radius=0)
        scroll.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 24))
        scroll.grid_columnconfigure((0, 1), weight=1)

        overview = self._card(scroll)
        overview.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(
            overview, text="What DropHound does", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")
        ).pack(anchor="w", padx=18, pady=(16, 6))
        ctk.CTkLabel(
            overview,
            text=(
                "DropHound is a friendly desktop interface powered by\n"
                f"Cyberdrop-DL {ENGINE_VERSION}. Downloads run locally on your computer."
            ),
            justify="left",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=18, pady=(0, 16))

        link_types = self._card(scroll)
        link_types.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(
            link_types, text="Common supported link types", text_color=TEXT, font=ctk.CTkFont(size=17, weight="bold")
        ).pack(anchor="w", padx=18, pady=(16, 6))
        ctk.CTkLabel(
            link_types,
            text=(
                "• Albums, galleries, posts, and forum threads\n"
                "• Direct image, video, audio, and archive links\n"
                "• Shared cloud files and folders\n"
                "• Supported social posts, profiles, and playlists"
            ),
            justify="left",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=18, pady=(0, 16))

        sites_card = self._card(scroll)
        sites_card.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(
            sites_card,
            text="Supported websites",
            text_color=TEXT,
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(16, 2))
        self.supported_sites_summary = ctk.CTkLabel(
            sites_card,
            text="Loading the list from the bundled downloader…",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        )
        self.supported_sites_summary.pack(anchor="w", padx=18, pady=(0, 8))
        self.supported_sites_text = ctk.CTkTextbox(
            sites_card,
            height=210,
            corner_radius=10,
            fg_color="#080D18",
            border_width=0,
            text_color="#CBD5E1",
            font=ctk.CTkFont(size=12),
            wrap="word",
        )
        self.supported_sites_text.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.supported_sites_text.insert(
            "1.0",
            "The complete list will appear here. Website support can change when the downloader engine is updated.",
        )
        self.supported_sites_text.configure(state="disabled")

        note = self._card(scroll)
        note.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(
            note,
            text="Use responsibly",
            text_color=TEXT,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(14, 3))
        ctk.CTkLabel(
            note,
            text=(
                "Only download material you own or have permission to save. Some links may require a cookies.txt "
                "file, and website changes can temporarily affect support."
            ),
            justify="left",
            wraplength=760,
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=18, pady=(0, 14))

    def _show_page(self, name: str) -> None:
        self.pages[name].tkraise()
        for key, button in self.nav_buttons.items():
            selected = key == name
            button.configure(
                fg_color=SURFACE_2 if selected else "transparent",
                text_color=TEXT if selected else MUTED,
            )
        if name == "history":
            self._refresh_history()
        elif name == "about" and not self.supported_sites_loaded:
            self.supported_sites_loaded = True
            threading.Thread(target=self._supported_sites_worker, daemon=True).start()

    def _supported_sites_worker(self) -> None:
        try:
            result = subprocess.run(
                supported_sites_command(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
                **process_startup_kwargs(),
            )
            sites = parse_supported_sites(result.stdout)
            if not sites:
                raise RuntimeError(result.stderr.strip() or "The downloader returned no supported sites.")
            self.events.put(("supported_sites", sites))
        except Exception as error:
            self.events.put(("supported_sites_error", str(error)))

    def _load_settings_into_ui(self) -> None:
        self.download_folder_var.set(self.settings.download_folder)
        self.cookies_var.set(self.settings.cookies_path)
        self.images_var.set(self.settings.images)
        self.videos_var.set(self.settings.videos)
        self.audio_var.set(self.settings.audio)
        self.other_var.set(self.settings.other)
        self.deep_scrape_var.set(self.settings.deep_scrape)
        self.ignore_history_var.set(self.settings.ignore_history)
        self.concurrent_var.set(self.settings.concurrent_downloads)
        self.per_domain_var.set(self.settings.per_domain)

    def _collect_settings(self) -> Settings:
        folder = self.download_folder_var.get().strip()
        if not folder:
            raise ValueError("Choose a download folder.")
        concurrent = int(self.concurrent_var.get())
        per_domain = int(self.per_domain_var.get())
        if concurrent < 1 or concurrent > 50 or per_domain < 1 or per_domain > 20:
            raise ValueError("Connection limits are outside the allowed range.")
        if per_domain > concurrent:
            raise ValueError("The per-website limit cannot exceed the total connection limit.")
        if not any((self.images_var.get(), self.videos_var.get(), self.audio_var.get(), self.other_var.get())):
            raise ValueError("Select at least one file type.")
        cookies = self.cookies_var.get().strip()
        if cookies and not Path(cookies).is_file():
            raise ValueError("The selected cookies file does not exist.")
        return Settings(
            download_folder=folder,
            cookies_path=cookies,
            images=self.images_var.get(),
            videos=self.videos_var.get(),
            audio=self.audio_var.get(),
            other=self.other_var.get(),
            deep_scrape=self.deep_scrape_var.get(),
            ignore_history=self.ignore_history_var.get(),
            concurrent_downloads=concurrent,
            per_domain=per_domain,
        )

    def _save_settings(self, show_confirmation: bool = True) -> bool:
        try:
            self.settings = self._collect_settings()
            self.settings.save(self.settings_path)
            write_engine_config(self.settings, self.engine_config_path)
        except (ValueError, OSError) as error:
            messagebox.showerror("Could not save settings", str(error), parent=self)
            return False
        if show_confirmation:
            self.run_status.configure(text="Settings saved", text_color=SUCCESS)
        return True

    def _browse_download_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.download_folder_var.get() or None, parent=self)
        if chosen:
            self.download_folder_var.set(chosen)

    def _browse_cookies(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Choose cookies.txt",
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
            parent=self,
        )
        if chosen:
            self.cookies_var.set(chosen)

    def _open_download_folder(self) -> None:
        folder = Path(self.download_folder_var.get())
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _start_download(self) -> None:
        try:
            entered_text = "" if self.urls_example_active else self.urls_text.get("1.0", "end")
            urls = normalize_urls(entered_text)
            if not urls:
                raise ValueError("Paste at least one link to download.")
        except ValueError as error:
            messagebox.showerror("Check the links", str(error), parent=self)
            return
        if not self._save_settings(show_confirmation=False):
            return
        try:
            command = download_command(urls, self.engine_config_path)
        except FileNotFoundError as error:
            messagebox.showerror("Downloader missing", str(error), parent=self)
            return
        self._launch(command, len(urls), "Starting download…")

    def _show_urls_example(self) -> None:
        self.urls_text.delete("1.0", "end")
        self.urls_text.insert("1.0", URLS_EXAMPLE)
        self.urls_text.configure(text_color=MUTED)
        self.urls_example_active = True

    def _clear_urls_example(self, _event: object | None = None) -> None:
        if not self.urls_example_active:
            return
        self.urls_text.delete("1.0", "end")
        self.urls_text.configure(text_color=TEXT)
        self.urls_example_active = False

    def _restore_urls_example(self, _event: object | None = None) -> None:
        if not self.urls_text.get("1.0", "end").strip():
            self._show_urls_example()

    def _clear_urls(self) -> None:
        self._show_urls_example()

    def _retry_failed(self) -> None:
        if not self._save_settings(show_confirmation=False):
            return
        try:
            command = retry_failed_command(self.engine_config_path)
        except FileNotFoundError as error:
            messagebox.showerror("Downloader missing", str(error), parent=self)
            return
        self._launch(command, 0, "Retrying failed downloads…")

    def _launch(self, command: list[str], url_count: int, message: str) -> None:
        if self.process is not None:
            messagebox.showinfo("Download already running", "Wait for the current run or cancel it.", parent=self)
            return
        self.cancel_requested = False
        self.telemetry_stop.set()
        self.telemetry_stop = threading.Event()
        self.telemetry_started = False
        self.transferred_bytes = 0
        self.peak_speed = 0.0
        self.transfer_graph.clear()
        self.file_progress_total = 0
        self.file_progress_label.configure(text="FILES  Discovering…", text_color=MUTED)
        self.downloaded_files_value.configure(text="0")
        self.queued_files_value.configure(text="0")
        self.failed_files_value.configure(text="0")
        self.skipped_files_value.configure(text="0")
        self._update_metric_labels(0.0, 0.0, 0.0)
        self.started_at = utc_now()
        self.active_url_count = url_count
        self._set_running(True)
        self._append_log(message)
        self.run_status.configure(text=message, text_color=ACCENT)
        threading.Thread(target=self._worker, args=(command,), daemon=True).start()

    def _worker(self, command: list[str]) -> None:
        try:
            environment = os.environ.copy()
            environment["CDL_WRITE_JSON_UI"] = "1"
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
                **process_startup_kwargs(),
            )
            self.events.put(("process", process))
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = clean_output(raw_line)
                if line:
                    progress = parse_file_progress(line)
                    self.events.put(("file_progress", progress) if progress is not None else ("log", line))
            self.events.put(("done", process.wait()))
        except Exception as error:
            self.events.put(("error", str(error)))

    def _cancel(self) -> None:
        if self.process is None:
            return
        self.cancel_requested = True
        self.run_status.configure(text="Cancelling…", text_color=DANGER)
        self._append_log("Cancellation requested. Stopping the downloader…")
        self.process.terminate()
        self.after(5000, self._force_kill_if_running)

    def _force_kill_if_running(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()

    def _poll_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "process":
                    self.process = value  # type: ignore[assignment]
                    self._start_telemetry()
                elif event == "log":
                    self._append_log(str(value))
                    self.run_status.configure(text=str(value)[:80], text_color=MUTED)
                elif event == "file_progress":
                    self._apply_file_progress(value)
                elif event == "supported_sites":
                    self._show_supported_sites(value)
                elif event == "supported_sites_error":
                    self.supported_sites_summary.configure(text="Could not load the complete list.", text_color=DANGER)
                    self._set_supported_sites_text(
                        f"The supported-sites catalog could not be read.\n\n{value}\n\n"
                        "DropHound can still download links recognized by the bundled Cyberdrop-DL engine."
                    )
                elif event == "done":
                    self._finish(int(value))
                elif event == "telemetry":
                    self._apply_telemetry(value)  # type: ignore[arg-type]
                elif event == "error":
                    self._append_log(f"Could not start downloader: {value}")
                    self._finish(-1)
                    messagebox.showerror("Download error", str(value), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _start_telemetry(self) -> None:
        if self.telemetry_started:
            return
        self.telemetry_started = True
        threading.Thread(target=self._telemetry_worker, daemon=True).start()

    def _telemetry_worker(self) -> None:
        destination = Path(self.settings.download_folder)
        destination.mkdir(parents=True, exist_ok=True)
        previous_size = folder_size(destination)
        counters = psutil.disk_io_counters()
        previous_disk = counters.write_bytes if counters else 0
        previous_time = time.monotonic()
        started = previous_time
        while not self.telemetry_stop.wait(1.0):
            now = time.monotonic()
            interval = max(now - previous_time, 0.001)
            current_size = folder_size(destination)
            counters = psutil.disk_io_counters()
            current_disk = counters.write_bytes if counters else previous_disk
            size_delta = max(0, current_size - previous_size)
            self.events.put(
                (
                    "telemetry",
                    {
                        "speed": size_delta / interval,
                        "disk": max(0, current_disk - previous_disk) / interval,
                        "bytes": size_delta,
                        "elapsed": now - started,
                    },
                )
            )
            previous_size = current_size
            previous_disk = current_disk
            previous_time = now

    def _apply_telemetry(self, payload: dict[str, float]) -> None:
        speed = float(payload["speed"])
        disk_speed = float(payload["disk"])
        self.transferred_bytes += int(payload["bytes"])
        self.peak_speed = max(self.peak_speed, speed)
        self.transfer_graph.push(speed, disk_speed)
        self._update_metric_labels(speed, disk_speed, float(payload["elapsed"]))

    def _apply_file_progress(self, value: object) -> None:
        completed = int(getattr(value, "completed"))
        total = int(getattr(value, "total"))
        self.file_progress_total = max(self.file_progress_total, total)
        visible_total = self.file_progress_total
        if visible_total <= 0:
            self.file_progress_label.configure(text="FILES  Discovering…", text_color=MUTED)
            return
        completed = min(completed, visible_total)
        self.file_progress_label.configure(
            text=f"FILES  {completed:,} / {visible_total:,}",
            text_color=SUCCESS if completed == visible_total else TEXT,
        )
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(completed / visible_total)
        self.downloaded_files_value.configure(text=f"{int(getattr(value, 'downloaded')):,}")
        self.queued_files_value.configure(text=f"{int(getattr(value, 'queued')):,}")
        self.failed_files_value.configure(text=f"{int(getattr(value, 'failed')):,}")
        skipped = int(getattr(value, "skipped")) + int(getattr(value, "previously_downloaded"))
        self.skipped_files_value.configure(text=f"{skipped:,}")

    def _show_supported_sites(self, value: object) -> None:
        sites = [str(site) for site in value]  # type: ignore[union-attr]
        self.supported_sites_summary.configure(
            text=f"{len(sites):,} site handlers included with Cyberdrop-DL {ENGINE_VERSION}",
            text_color=SUCCESS,
        )
        self._set_supported_sites_text("  •  ".join(sites))

    def _set_supported_sites_text(self, text: str) -> None:
        self.supported_sites_text.configure(state="normal")
        self.supported_sites_text.delete("1.0", "end")
        self.supported_sites_text.insert("1.0", text)
        self.supported_sites_text.configure(state="disabled")

    def _update_metric_labels(self, speed: float, disk_speed: float, elapsed: float) -> None:
        self.current_speed_value.configure(text=format_speed(speed))
        self.peak_speed_value.configure(text=format_speed(self.peak_speed))
        self.total_value.configure(text=format_bytes(self.transferred_bytes))
        self.disk_speed_value.configure(text=format_speed(disk_speed))
        self.elapsed_value.configure(text=format_elapsed(elapsed))

    def _finish(self, exit_code: int) -> None:
        self.telemetry_stop.set()
        status = "Cancelled" if self.cancel_requested else "Completed" if exit_code == 0 else "Failed"
        self.history.append(
            HistoryEntry(
                started_at=self.started_at,
                finished_at=utc_now(),
                status=status,
                url_count=self.active_url_count,
                download_folder=self.settings.download_folder,
                exit_code=exit_code,
            )
        )
        self.process = None
        self._set_running(False)
        color = SUCCESS if status == "Completed" else DANGER if status == "Failed" else MUTED
        self.run_status.configure(text=status, text_color=color)
        if self.file_progress_total == 0:
            self.file_progress_label.configure(text="FILES  None found", text_color=MUTED)
        self._append_log(f"Run {status.lower()}.")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.download_button.configure(state=state)
        self.retry_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.core_status.configure(text="●  Working" if running else "●  Ready", text_color=ACCENT if running else SUCCESS)
        if running:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            if self.file_progress_total == 0:
                self.progress.set(0)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_history(self) -> None:
        for child in self.history_list.winfo_children():
            child.destroy()
        entries = self.history.load()
        if not entries:
            empty = self._card(self.history_list)
            empty.pack(fill="x", padx=10, pady=10)
            ctk.CTkLabel(
                empty,
                text="No downloads yet",
                text_color=TEXT,
                font=ctk.CTkFont(size=16, weight="bold"),
            ).pack(pady=(28, 4))
            ctk.CTkLabel(
                empty,
                text="Completed runs will appear here.",
                text_color=MUTED,
            ).pack(pady=(0, 28))
            return
        for entry in entries:
            row = self._card(self.history_list)
            row.pack(fill="x", padx=10, pady=6)
            row.grid_columnconfigure(1, weight=1)
            color = SUCCESS if entry.status == "Completed" else DANGER if entry.status == "Failed" else MUTED
            ctk.CTkLabel(
                row,
                text=entry.status.upper(),
                width=92,
                height=30,
                corner_radius=8,
                fg_color=color,
                text_color="white",
                font=ctk.CTkFont(size=10, weight="bold"),
            ).grid(row=0, column=0, rowspan=2, padx=16, pady=16)
            started = entry.started_at.replace("T", " ").replace("+00:00", " UTC")
            ctk.CTkLabel(
                row,
                text=entry.download_folder,
                text_color=TEXT,
                font=ctk.CTkFont(size=13, weight="bold"),
            ).grid(row=0, column=1, sticky="sw", pady=(13, 1))
            ctk.CTkLabel(
                row,
                text=f"{started}   •   {entry.url_count or 'Retry'} links",
                text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).grid(row=1, column=1, sticky="nw", pady=(1, 13))

    def _on_close(self) -> None:
        if self.process is not None:
            if not messagebox.askyesno(
                "Download still running",
                "Cancel the active download and close DropHound?",
                parent=self,
            ):
                return
            self._cancel()
        self.telemetry_stop.set()
        self.destroy()


def main() -> None:
    DropHound().mainloop()
