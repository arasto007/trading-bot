"""Phase 8.1 preflight checks before production dataset build."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.collection_validation import MINIMUM_BAR_COUNTS, minimum_bar_count
from tradingbot.ml.data.paths import candle_path
from tradingbot.ml.data.roles import CONTEXT_TIMEFRAME, ENTRY_TIMEFRAME, HIGHER_TIMEFRAME_BIAS
from tradingbot.ml.data.stores import CandleStore

REQUIRED_TIMEFRAMES: tuple[str, ...] = (ENTRY_TIMEFRAME, CONTEXT_TIMEFRAME, HIGHER_TIMEFRAME_BIAS)
MIN_OVERLAP_DAYS = 30


def _norm_tf(timeframe: str) -> str:
    key = timeframe.strip().upper()
    return {"5M": "M5", "15M": "M15", "4H": "H4", "1M": "M1"}.get(key, key)


def _bounds(df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return None, None
    idx = df.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    return idx.min(), idx.max()


@dataclass
class TimeframePreflightStatus:
    timeframe: str
    available: bool
    row_count: int = 0
    minimum_required: int | None = None
    meets_minimum: bool = False
    storage_path: str | None = None
    start_utc: str | None = None
    end_utc: str | None = None
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreflightReport:
    symbol: str
    generated_at_utc: str
    overall: str
    timeframes: dict[str, TimeframePreflightStatus] = field(default_factory=dict)
    overlap_start_utc: str | None = None
    overlap_end_utc: str | None = None
    overlap_days: float = 0.0
    overlap_ok: bool = False
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.overall == "pass"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timeframes"] = {k: v.to_dict() for k, v in self.timeframes.items()}
        payload["passed"] = self.passed
        return payload


def run_preflight(
    symbol: str,
    *,
    base_dir: str | Path | None = None,
    timeframes: tuple[str, ...] | None = None,
    minimum_overrides: dict[str, int] | None = None,
    min_overlap_days: float = MIN_OVERLAP_DAYS,
) -> PreflightReport:
    """
    Verify raw candle availability, minimum bar counts, and timeframe overlap.

    Does not connect to MT5 or modify trading layers.
    """
    sym = symbol.upper()
    tfs = tuple(_norm_tf(tf) for tf in (timeframes or REQUIRED_TIMEFRAMES))
    now = datetime.now(timezone.utc).isoformat()
    report = PreflightReport(symbol=sym, generated_at_utc=now, overall="pass")

    store = CandleStore(base_dir)
    bounds: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {}

    for tf in tfs:
        min_required = (minimum_overrides or {}).get(tf, minimum_bar_count(tf))
        status = TimeframePreflightStatus(
            timeframe=tf,
            available=False,
            minimum_required=min_required,
        )
        path = candle_path(sym, tf, base_dir)
        status.storage_path = str(path)

        df = store.load(sym, tf)
        if df is None or df.empty:
            status.issues.append("no_data")
            report.issues.append(f"{tf}: no raw candle data")
            report.overall = "fail"
        else:
            status.available = True
            status.row_count = len(df)
            start, end = _bounds(df)
            if start is not None:
                status.start_utc = start.isoformat()
            if end is not None:
                status.end_utc = end.isoformat()
            bounds[tf] = (start, end)

            if min_required is not None and status.row_count < min_required:
                status.meets_minimum = False
                status.issues.append(f"below_minimum:{status.row_count}<{min_required}")
                report.issues.append(f"{tf}: {status.row_count} bars < minimum {min_required}")
                report.overall = "fail"
            else:
                status.meets_minimum = True

        report.timeframes[tf] = status

    starts = [bounds[tf][0] for tf in tfs if tf in bounds and bounds[tf][0] is not None]
    ends = [bounds[tf][1] for tf in tfs if tf in bounds and bounds[tf][1] is not None]
    if len(starts) == len(tfs) and len(ends) == len(tfs):
        overlap_start = max(starts)
        overlap_end = min(ends)
        report.overlap_start_utc = overlap_start.isoformat()
        report.overlap_end_utc = overlap_end.isoformat()
        delta = overlap_end - overlap_start
        report.overlap_days = float(delta.total_seconds() / 86400.0)
        report.overlap_ok = overlap_start < overlap_end and report.overlap_days >= min_overlap_days
        if not report.overlap_ok:
            report.issues.append(
                f"insufficient overlap: {report.overlap_days:.1f} days (need >= {min_overlap_days})"
            )
            report.overall = "fail"
    elif report.overall != "fail":
        report.overall = "fail"
        report.issues.append("cannot compute overlap — missing timeframe bounds")

    return report
