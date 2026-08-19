"""Phase 22F — rapid validation config."""

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
TARGET_RUNTIME_MIN = 5
TARGET_RUNTIME_MAX = 15

DATASET_TRADING_DAYS = {"A": 7, "B": 14, "C": 30}


@dataclass(frozen=True)
class RapidDataset:
    label: str
    trading_days: int
    start: datetime
    end: datetime

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "trading_days": self.trading_days,
            "start_tehran": self.start.strftime("%Y-%m-%d %H:%M"),
            "end_tehran": self.end.strftime("%Y-%m-%d %H:%M"),
        }


def configure_research_env() -> None:
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ["TREND_MODEL_VERSION"] = "v41"
    os.environ.setdefault("PHASE22C_ENABLED", "true")
    os.environ["TRADINGBOT_DRY_RUN"] = "1"


def _count_trading_days_back(end_date, n: int):
    d = end_date
    counted = 0
    while counted < n:
        if d.weekday() < 5:
            counted += 1
        if counted < n:
            d -= timedelta(days=1)
    return d


def build_dataset(label: str, *, end: datetime | None = None) -> RapidDataset:
    if label not in DATASET_TRADING_DAYS:
        raise ValueError(f"Unknown dataset {label!r}; use A, B, or C")
    days = DATASET_TRADING_DAYS[label]
    end = (end or datetime.now(TEHRAN)).astimezone(TEHRAN)
    end_dt = datetime.combine(end.date(), time(23, 59), tzinfo=TEHRAN)
    start_date = _count_trading_days_back(end.date(), days)
    start = datetime.combine(start_date, time(0, 0), tzinfo=TEHRAN)
    return RapidDataset(label=label, trading_days=days, start=start, end=end_dt)


def data_window_days(tf: str, start: datetime, end: datetime, now_tehran: datetime) -> tuple[int, int]:
    pad = WARMUP_PAD_DAYS.get(tf, 7)
    days = max((now_tehran.date() - start.date()).days + pad + 2, pad + 3)
    return days, 0
