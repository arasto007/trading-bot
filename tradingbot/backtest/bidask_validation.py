"""Bid/ask dataset validation and spread quality reporting — no synthetic data."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.cost_model import SpreadMode, validate_dataset_spread


@dataclass
class BidAskValidationResult:
    ok: bool
    row_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timezone: str = "unknown"
    date_start: str | None = None
    date_end: str | None = None
    duplicate_timestamps: int = 0
    missing_bid: int = 0
    missing_ask: int = 0
    negative_spread_count: int = 0
    zero_spread_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SpreadQualityReport:
    schema_version: int = 1
    generated_at: str = ""
    dataset_path: str = ""
    symbol: str = ""
    source: str = "mt5_copy_ticks_range"
    evidence_timestamp: str = ""
    spread_classification: str = "OBSERVED_DATASET_SPREAD"
    row_count: int = 0
    valid_row_count: int = 0
    invalid_row_count: int = 0
    spread_mode: str = SpreadMode.DATASET.value
    spread_source: str = "BID_ASK_OBSERVED"
    min_spread: float | None = None
    max_spread: float | None = None
    mean_spread: float | None = None
    median_spread: float | None = None
    p95_spread: float | None = None
    p99_spread: float | None = None
    zero_spread_count: int = 0
    negative_spread_count: int = 0
    missing_bid_count: int = 0
    missing_ask_count: int = 0
    outlier_count: int = 0
    unit: str = "price"
    date_range_utc: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _col(df: pd.DataFrame, name: str) -> str | None:
    for c in df.columns:
        if str(c).lower() == name.lower():
            return str(c)
    return None


def validate_bidask_dataset(
    df: pd.DataFrame,
    *,
    outlier_p99_multiplier: float = 5.0,
) -> BidAskValidationResult:
    """Validate timestamps, bid/ask, spread — fail closed on critical errors."""
    result = BidAskValidationResult(ok=True, row_count=len(df))
    if df is None or df.empty:
        result.ok = False
        result.errors.append("empty_frame")
        return result

    if not isinstance(df.index, pd.DatetimeIndex):
        result.ok = False
        result.errors.append("index_not_datetime")
        return result

    tz = getattr(df.index, "tz", None)
    result.timezone = str(tz) if tz is not None else "naive"
    result.date_start = str(df.index[0])
    result.date_end = str(df.index[-1])

    if not df.index.is_monotonic_increasing:
        result.ok = False
        result.errors.append("timestamps_not_monotonic")

    dup = int(df.index.duplicated().sum())
    result.duplicate_timestamps = dup
    if dup > 0:
        result.ok = False
        result.errors.append("duplicate_timestamps")

    bid_col = _col(df, "bid")
    ask_col = _col(df, "ask")
    if bid_col is None:
        result.ok = False
        result.errors.append("missing_bid_column")
    if ask_col is None:
        result.ok = False
        result.errors.append("missing_ask_column")
    if bid_col is None or ask_col is None:
        return result

    bid = pd.to_numeric(df[bid_col], errors="coerce")
    ask = pd.to_numeric(df[ask_col], errors="coerce")
    result.missing_bid = int(bid.isna().sum())
    result.missing_ask = int(ask.isna().sum())
    if result.missing_bid or result.missing_ask:
        result.ok = False
        result.errors.append("missing_bid_or_ask_values")

    spread = ask - bid
    result.negative_spread_count = int((spread < 0).sum())
    result.zero_spread_count = int((spread == 0).sum())
    if result.negative_spread_count > 0:
        result.ok = False
        result.errors.append("negative_spread")

    spread_check = validate_dataset_spread(df)
    if spread_check.spread_mode != SpreadMode.DATASET:
        result.ok = False
        result.errors.append(f"spread_not_dataset:{spread_check.spread_source}")

    valid = spread.dropna()
    if not valid.empty:
        p99 = float(valid.quantile(0.99))
        outliers = int((valid > p99 * outlier_p99_multiplier).sum())
        if outliers:
            result.warnings.append(f"spread_outliers:{outliers}")

    return result


def compute_spread_quality(
    df: pd.DataFrame,
    *,
    dataset_path: str | Path = "",
    symbol: str = "XAUUSD_i",
    source: str = "mt5_copy_ticks_range",
    validation: BidAskValidationResult | None = None,
) -> SpreadQualityReport:
    """Compute spread statistics for observed bid/ask dataset."""
    bid_col = _col(df, "bid")
    ask_col = _col(df, "ask")
    if bid_col is None or ask_col is None:
        return SpreadQualityReport(
            generated_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            dataset_path=str(dataset_path),
            symbol=symbol,
            row_count=len(df),
            spread_mode=SpreadMode.UNKNOWN.value,
        )

    bid = pd.to_numeric(df[bid_col], errors="coerce")
    ask = pd.to_numeric(df[ask_col], errors="coerce")
    spread = (ask - bid).dropna()
    valid_mask = bid.notna() & ask.notna() & (ask >= bid)
    valid_count = int(valid_mask.sum())
    invalid_count = int(len(df) - valid_count)
    p95 = float(spread.quantile(0.95)) if not spread.empty else None
    p99 = float(spread.quantile(0.99)) if not spread.empty else None
    outlier_count = 0
    if p99 is not None and p99 > 0:
        outlier_count = int((spread > p99 * 5).sum())

    tz = getattr(df.index, "tz", None)
    return SpreadQualityReport(
        generated_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        evidence_timestamp=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        dataset_path=str(dataset_path),
        symbol=symbol,
        source=source,
        row_count=len(df),
        valid_row_count=valid_count,
        invalid_row_count=invalid_count,
        spread_mode=SpreadMode.DATASET.value,
        spread_source="BID_ASK_OBSERVED",
        spread_classification="OBSERVED_DATASET_SPREAD",
        min_spread=float(spread.min()) if not spread.empty else None,
        max_spread=float(spread.max()) if not spread.empty else None,
        mean_spread=float(spread.mean()) if not spread.empty else None,
        median_spread=float(spread.median()) if not spread.empty else None,
        p95_spread=p95,
        p99_spread=p99,
        zero_spread_count=int((spread == 0).sum()),
        negative_spread_count=int((spread < 0).sum()),
        missing_bid_count=int(bid.isna().sum()),
        missing_ask_count=int(ask.isna().sum()),
        outlier_count=outlier_count,
        unit="price",
        date_range_utc={
            "start": str(df.index[0]),
            "end": str(df.index[-1]),
            "timezone": str(tz) if tz is not None else "naive",
        },
    )


def write_spread_quality_report(report: SpreadQualityReport, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return out
