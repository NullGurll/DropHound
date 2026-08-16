from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

APP_NAME = "DropHound"
ENGINE_VERSION = "10.3.0"
ANSI_ESCAPE = re.compile(r"(?:\x1B[@-_][0-?]*[ -/]*[@-~])|(?:\x1B\][^\x07]*(?:\x07|\x1B\\))")


def app_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def default_download_dir() -> Path:
    profile = Path(os.environ.get("USERPROFILE", Path.home())) if sys.platform == "win32" else Path.home()
    return profile / "Downloads" / "DropHound"


@dataclass
class Settings:
    download_folder: str
    cookies_path: str = ""
    images: bool = True
    videos: bool = True
    audio: bool = True
    other: bool = True
    deep_scrape: bool = False
    ignore_history: bool = False
    concurrent_downloads: int = 15
    per_domain: int = 5

    @classmethod
    def defaults(cls) -> "Settings":
        return cls(download_folder=str(default_download_dir()))

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            defaults = asdict(cls.defaults())
            return cls(**(defaults | {key: value for key, value in raw.items() if key in defaults}))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return cls.defaults()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


@dataclass
class HistoryEntry:
    started_at: str
    finished_at: str
    status: str
    url_count: int
    download_folder: str
    exit_code: int | None


@dataclass(frozen=True)
class FileProgress:
    completed: int
    total: int
    downloaded: int
    queued: int
    skipped: int
    failed: int
    previously_downloaded: int


@dataclass(frozen=True)
class ImageScanProgress:
    total: int
    scraping: int
    downloading: int
    errors: int


def parse_file_progress(line: str) -> FileProgress | None:
    """Read Cyberdrop-DL's structured UI snapshot without depending on display text."""
    try:
        payload = json.loads(line)
        files = payload["files"]
        downloaded = max(0, int(files.get("completed", 0)))
        skipped = max(0, int(files.get("skipped", 0)))
        failed = max(0, int(files.get("failed", 0)))
        previously_downloaded = max(0, int(files.get("prev_completed", 0)))
        queued = max(0, int(files.get("queued", 0)))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None

    completed = downloaded + skipped + failed + previously_downloaded
    return FileProgress(
        completed=completed,
        total=completed + queued,
        downloaded=downloaded,
        queued=queued,
        skipped=skipped,
        failed=failed,
        previously_downloaded=previously_downloaded,
    )


def parse_image_scan_progress(line: str) -> ImageScanProgress | None:
    """Read the image-discovery state from Cyberdrop-DL's structured UI."""
    try:
        payload = json.loads(line)
        files = payload["files"]
        total = sum(
            max(0, int(files.get(name, 0)))
            for name in ("completed", "prev_completed", "failed", "queued")
        )
        scraping = len(payload.get("scraping", ()))
        downloading = len(payload.get("downloads", ()))
        scrape_errors = payload.get("scrape_errors", {}).get("errors", ())
        download_errors = payload.get("download_errors", {}).get("errors", ())
        errors = len(scrape_errors) + len(download_errors)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    return ImageScanProgress(
        total=total,
        scraping=scraping,
        downloading=downloading,
        errors=errors,
    )


def parse_supported_sites(output: str) -> list[str]:
    """Extract the authoritative site names returned by Cyberdrop-DL."""
    try:
        payload = json.loads(clean_output(output))
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    return sorted((str(name) for name in payload), key=str.casefold)


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[HistoryEntry]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
            return [HistoryEntry(**item) for item in items if isinstance(item, dict)]
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return []

    def append(self, entry: HistoryEntry) -> None:
        items = self.load()
        items.insert(0, entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([asdict(item) for item in items[:100]], indent=2),
            encoding="utf-8",
        )


def normalize_urls(text: str) -> list[str]:
    candidates = re.split(r"[\s,]+", text.strip())
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = candidate.strip()
        if not value or value in seen:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Not a valid web link: {value}")
        seen.add(value)
        result.append(value)
    return result


def yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_engine_config(settings: Settings, path: Path) -> None:
    cookies = "null" if not settings.cookies_path else yaml_scalar(settings.cookies_path)
    content = f"""\
cookies: {cookies}
deep_scrape: {str(settings.deep_scrape).lower()}
download_folder: {yaml_scalar(settings.download_folder)}
downloads:
  concurrency: {settings.concurrent_downloads}
  concurrency_per_domain: {settings.per_domain}
filters:
  files:
    audio: {str(settings.audio).lower()}
    images: {str(settings.images).lower()}
    non_media: {str(settings.other).lower()}
    videos: {str(settings.videos).lower()}
ignore_history: {str(settings.ignore_history).lower()}
ui:
  mode: activity
  show_stats: true
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def engine_command() -> list[str]:
    if getattr(sys, "frozen", False):
        filename = "DropHoundEngine.exe" if sys.platform == "win32" else "DropHoundEngine"
        engine = Path(sys.executable).with_name(filename)
        if not engine.exists():
            raise FileNotFoundError(f"{filename} is missing from the application folder.")
        return [str(engine)]
    return [sys.executable, "-m", "cyberdrop_dl"]


def write_url_batch(urls: Iterable[str], path: Path) -> Path:
    """Write one URL per line for Cyberdrop-DL's reliable bulk-input mode."""
    values = [url.strip() for url in urls if url.strip()]
    if not values:
        raise ValueError("Paste at least one link to download.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(values) + "\n", encoding="utf-8")
    return path


def download_command(urls: Iterable[str], config_path: Path) -> list[str]:
    batch_path = write_url_batch(urls, config_path.with_name("active-links.txt"))
    return [*engine_command(), "download", "--input-file", str(batch_path), "--config", str(config_path)]


def image_scan_command(urls: Iterable[str], config_path: Path) -> list[str]:
    """Discover images with an isolated, deliberately throttled engine run."""
    batch_path = write_url_batch(urls, config_path.with_name("scan-links.txt"))
    return [
        *engine_command(),
        "download",
        "--input-file",
        str(batch_path),
        "--config",
        str(config_path),
        "--images",
        "--no-videos",
        "--no-audio",
        "--no-non-media",
        "--speed-limit",
        "1B",
    ]


def retry_failed_command(config_path: Path) -> list[str]:
    return [*engine_command(), "retry", "failed", "--config", str(config_path)]


def supported_sites_command() -> list[str]:
    return [*engine_command(), "show", "--json"]


def clean_output(line: str) -> str:
    return ANSI_ESCAPE.sub("", line).replace("\r", "").strip()


def process_startup_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
