"""توقف دستی ربات — فلگ برای جلوگیری از ری‌استارت خودکار watchdog."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLAG_PATH = ROOT / "data" / "manual_stop.flag"


def set_manual_stop(reason: str = "user") -> None:
    FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()}|{reason}"
    FLAG_PATH.write_text(line + "\n", encoding="ascii", errors="replace")


def clear_manual_stop() -> None:
    try:
        FLAG_PATH.unlink()
    except FileNotFoundError:
        pass


def is_manual_stop() -> bool:
    return FLAG_PATH.is_file()


def read_manual_stop() -> str | None:
    if not FLAG_PATH.is_file():
        return None
    text = FLAG_PATH.read_text(encoding="utf-8").strip()
    return text.lstrip("\ufeff").strip()
