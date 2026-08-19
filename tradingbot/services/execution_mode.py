"""حالت‌های اجرا: dry-run، paper، live."""

from __future__ import annotations

import os


def is_dry_run() -> bool:
    return os.getenv("TRADINGBOT_DRY_RUN", "").lower() in ("1", "true", "yes")


def is_paper() -> bool:
    return os.getenv("TRADINGBOT_PAPER", "").lower() in ("1", "true", "yes")


def is_live_execute() -> bool:
    return not is_dry_run() and not is_paper()


def mode_label() -> str:
    if is_paper():
        return "paper"
    if is_dry_run():
        return "dry_run"
    return "live"
