"""Rotating JSONL writers — keep hot logs from unbounded growth."""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any

MAX_BYTES = 50 * 1024 * 1024
BACKUP_COUNT = 7
ENCODING = "utf-8"

_lock = Lock()
_handlers: dict[str, RotatingFileHandler] = {}


def rotating_handler(path: Path | str) -> RotatingFileHandler:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    key = str(target.resolve())
    with _lock:
        handler = _handlers.get(key)
        if handler is None:
            handler = RotatingFileHandler(
                str(target),
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding=ENCODING,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            _handlers[key] = handler
        return handler


def append_rotating_jsonl(path: Path | str, row: dict[str, Any]) -> None:
    """Append one JSON object as a line, rotating at 50MB (7 backups)."""
    line = json.dumps(row, ensure_ascii=False, default=str)
    handler = rotating_handler(path)
    record = logging.LogRecord(
        name="jsonl",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=line,
        args=(),
        exc_info=None,
    )
    handler.emit(record)


def rotation_active(path: Path | str) -> bool:
    handler = rotating_handler(path)
    return (
        isinstance(handler, RotatingFileHandler)
        and int(handler.maxBytes) == MAX_BYTES
        and int(handler.backupCount) == BACKUP_COUNT
    )