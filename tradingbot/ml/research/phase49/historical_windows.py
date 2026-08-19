"""Phase 49 — historical window builders for ML signal capture."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from tradingbot.ml.research.phase22f.config import RapidDataset

TEHRAN = ZoneInfo("Asia/Tehran")

_QUARTER_END = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}

_QUARTER_START = {
    1: (1, 1),
    2: (4, 1),
    3: (7, 1),
    4: (10, 1),
}


def build_quarter_dataset(year: int, quarter: int) -> RapidDataset:
    if quarter not in _QUARTER_END:
        raise ValueError(f"quarter must be 1-4, got {quarter}")
    sm, sd = _QUARTER_START[quarter]
    em, ed = _QUARTER_END[quarter]
    start = datetime(year, sm, sd, 0, 0, tzinfo=TEHRAN)
    end = datetime(year, em, ed, 23, 59, tzinfo=TEHRAN)
    label = f"Y{year}Q{quarter}"
    days = max((end.date() - start.date()).days, 1)
    return RapidDataset(label=label, trading_days=days, start=start, end=end)


def quarter_labels(year_start: int = 2021, year_end: int = 2026) -> list[str]:
    out: list[str] = []
    for year in range(year_start, year_end + 1):
        for q in (1, 2, 3, 4):
            if year == 2026 and q > 2:
                continue
            out.append(f"Y{year}Q{q}")
    return out
