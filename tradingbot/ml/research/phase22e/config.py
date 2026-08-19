"""Phase 22E — validation windows, success criteria, production env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
SYMBOL = "XAUUSD"
TIMEFRAMES = ("M5", "M15", "H4")
BALANCE = 200.0
WARMUP_PAD_DAYS = {"M5": 4, "M15": 6, "H4": 65}

WINDOW_LABELS = ("1m", "3m", "6m", "1y", "3y")
WINDOW_DAYS = {"1m": 30, "3m": 91, "6m": 182, "1y": 365, "3y": 1095}

PF_TARGET = 1.30
MAX_DRAWDOWN_PCT_LIMIT = 25.0
MONTE_CARLO_SIMS = 1000
WALK_FORWARD_FOLDS = 4
DEFAULT_SEED = 42


@dataclass(frozen=True)
class ValidationWindow:
    label: str
    start: datetime
    end: datetime

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "start_tehran": self.start.strftime("%Y-%m-%d %H:%M"),
            "end_tehran": self.end.strftime("%Y-%m-%d %H:%M"),
        }


def compute_windows(*, end: datetime | None = None) -> list[ValidationWindow]:
    """Calendar-aligned Tehran windows (00:00 start, 23:59 end)."""
    if end is None:
        end = datetime.now(TEHRAN)
    else:
        end = end.astimezone(TEHRAN)
    end = datetime.combine(end.date(), time(23, 59), tzinfo=TEHRAN)
    windows: list[ValidationWindow] = []
    for label in WINDOW_LABELS:
        days = WINDOW_DAYS[label]
        start_date = end.date() - timedelta(days=days)
        start = datetime.combine(start_date, time(0, 0), tzinfo=TEHRAN)
        windows.append(ValidationWindow(label=label, start=start, end=end))
    return windows


def configure_production_env() -> None:
    """Ensure Phase 22D production path is active (no threshold tuning in 22E)."""
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ["TREND_MODEL_VERSION"] = "v41"
    os.environ.setdefault("PHASE22C_ENABLED", "true")
    os.environ["TRADINGBOT_DRY_RUN"] = "1"


def data_window_days(tf: str, start: datetime, end: datetime, now_tehran: datetime) -> tuple[int, int]:
    pad = WARMUP_PAD_DAYS.get(tf, 7)
    days = max((now_tehran.date() - start.date()).days + pad + 2, pad + 3)
    return days, 0
