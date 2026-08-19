"""Append-only signal filter rejection log."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_rejections: list[dict[str, Any]] = []


def log_rejection(record: dict[str, Any]) -> None:
    with _lock:
        _rejections.append(record)


def export_log(path: str | Path) -> int:
    with _lock:
        payload = {"rejections": list(_rejections), "count": len(_rejections)}
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return len(_rejections)


def clear_log() -> None:
    with _lock:
        _rejections.clear()


def get_rejections() -> list[dict[str, Any]]:
    with _lock:
        return list(_rejections)
