"""
لاگ‌گیری تمیز و خودکفا — جایگزین engine.logger.

یک `get_logger(module, base_dir)` ساده که logger استاندارد می‌سازد:
- یک handler کنسول
- یک RotatingFileHandler در `{base_dir}/logs/{module}.log` (best-effort)

امضا با فراخوانی‌های موجود سازگار است: `get_logger("mt5_execution", base_dir)`.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Any

_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUPS = 5


def get_logger(
    module: str,
    base_dir: str = ".",
    symbol: str | None = None,
    timeframe: str | None = None,
    config: dict[str, Any] | None = None,
) -> logging.Logger:
    """logger با نام `TradingBot.{module}[.symbol[.timeframe]]` برمی‌گرداند.

    اگر logger قبلاً ساخته شده باشد، همان برگردانده می‌شود (بدون افزودن handler تکراری).
    """
    name = f"TradingBot.{module}"
    if symbol:
        name += f".{symbol}"
    if timeframe:
        name += f".{timeframe}"

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        log_dir = os.path.join(base_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, f"{module}.log"),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:  # noqa: BLE001
        # نبودِ فایل‌لاگ نباید اجرای ربات را متوقف کند.
        pass

    return logger
