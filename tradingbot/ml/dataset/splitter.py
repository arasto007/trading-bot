"""Chronological dataset splitting — no random shuffle."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_BAR_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


@dataclass
class SplitResult:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    train_end: pd.Timestamp | None
    val_end: pd.Timestamp | None
    purge_rows: int = 0


def bar_timedelta(timeframe: str, bars: int) -> pd.Timedelta:
    minutes = _BAR_MINUTES.get(timeframe.upper(), 5)
    return pd.Timedelta(minutes=minutes * bars)


def time_based_split(
    df: pd.DataFrame,
    *,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    timestamp_col: str = "timestamp",
    purge_bars: int = 0,
    timeframe: str = "M5",
) -> SplitResult:
    """
    Split dataset by datetime order.

    No shuffle. Earliest rows -> train, then validation, then test.
  Optional purge gap (in bars) between splits.
    """
    if df is None or df.empty:
        empty = pd.DataFrame()
        return SplitResult(empty, empty, empty, None, None)

    total_ratio = train_ratio + val_ratio + test_ratio
    if abs(total_ratio - 1.0) > 1e-6:
        raise ValueError(f"Split ratios must sum to 1.0, got {total_ratio}")

    work = assign_purged_split_column(
        df,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        timestamp_col=timestamp_col,
        purge_bars=purge_bars,
        timeframe=timeframe,
    )
    train = work[work["split"] == "train"].copy()
    val = work[work["split"] == "validation"].copy()
    test = work[work["split"] == "test"].copy()
    purge_count = int((work["split"] == "purge").sum()) if "split" in work.columns else 0

    ts = pd.to_datetime(work[timestamp_col], utc=True) if timestamp_col in work.columns else work.index
    train_end = ts[work["split"] == "train"].max() if not train.empty else None
    val_end = ts[work["split"] == "validation"].max() if not val.empty else train_end

    return SplitResult(
        train=train,
        validation=val,
        test=test,
        train_end=train_end,
        val_end=val_end,
        purge_rows=purge_count,
    )


def assign_purged_split_column(
    df: pd.DataFrame,
    *,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    timestamp_col: str = "timestamp",
    purge_bars: int = 72,
    timeframe: str = "M5",
) -> pd.DataFrame:
    """
    Add `split` column with optional purge gaps between train/validation/test.

    Rows in purge windows are marked `purge` and excluded from all splits.
    """
    if df is None or df.empty:
        return df

    work = df.copy()
    if timestamp_col in work.columns:
        work["_ts"] = pd.to_datetime(work[timestamp_col], utc=True)
    else:
        work["_ts"] = pd.to_datetime(work.index, utc=True)

    work = work.sort_values("_ts").reset_index(drop=True)
    n = len(work)
    target_train = int(n * train_ratio)
    target_val = int(n * val_ratio)
    purge_delta = bar_timedelta(timeframe, purge_bars) if purge_bars > 0 else pd.Timedelta(0)

    splits = ["purge"] * n
    i = 0

    # Train block
    train_assigned = 0
    while i < n and train_assigned < target_train:
        splits[i] = "train"
        train_assigned += 1
        i += 1

    if i < n and purge_bars > 0 and train_assigned > 0:
        purge_until = work["_ts"].iloc[i - 1] + purge_delta
        while i < n and work["_ts"].iloc[i] < purge_until:
            splits[i] = "purge"
            i += 1

    # Validation block
    val_assigned = 0
    while i < n and val_assigned < target_val:
        splits[i] = "validation"
        val_assigned += 1
        i += 1

    if i < n and purge_bars > 0 and val_assigned > 0:
        purge_until = work["_ts"].iloc[i - 1] + purge_delta
        while i < n and work["_ts"].iloc[i] < purge_until:
            splits[i] = "purge"
            i += 1

    # Test block — remainder
    while i < n:
        splits[i] = "test"
        i += 1

    work["split"] = splits
    return work.drop(columns=["_ts"])


def assign_split_column(
    df: pd.DataFrame,
    *,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    timestamp_col: str = "timestamp",
    purge_bars: int = 0,
    timeframe: str = "M5",
) -> pd.DataFrame:
    """Add `split` column: train | validation | test (no purge when purge_bars=0)."""
    return assign_purged_split_column(
        df,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        timestamp_col=timestamp_col,
        purge_bars=purge_bars,
        timeframe=timeframe,
    )


def verify_chronological_splits(df: pd.DataFrame, timestamp_col: str = "timestamp") -> bool:
    """Ensure train max < validation min < test min (excluding purge rows)."""
    if "split" not in df.columns or df.empty:
        return True
    ts = pd.to_datetime(df[timestamp_col], utc=True) if timestamp_col in df.columns else df.index
    work = df.copy()
    work["_ts"] = ts
    bounds: list[tuple[float, float]] = []
    for name in ("train", "validation", "test"):
        part = work[work["split"] == name]
        if part.empty:
            continue
        bounds.append((part["_ts"].min().timestamp(), part["_ts"].max().timestamp()))
    for i in range(len(bounds) - 1):
        if bounds[i][1] >= bounds[i + 1][0]:
            return False
    return True


def verify_purge_gaps(
    df: pd.DataFrame,
    *,
    purge_bars: int,
    timeframe: str = "M5",
    timestamp_col: str = "timestamp",
) -> bool:
    """Verify minimum time gap between split boundaries >= purge window."""
    if purge_bars <= 0 or "split" not in df.columns:
        return True
    ts = pd.to_datetime(df[timestamp_col], utc=True) if timestamp_col in df.columns else df.index
    work = df.assign(_ts=ts)
    purge_delta = bar_timedelta(timeframe, purge_bars)

    pairs = [("train", "validation"), ("validation", "test")]
    for left, right in pairs:
        left_part = work[work["split"] == left]
        right_part = work[work["split"] == right]
        if left_part.empty or right_part.empty:
            continue
        gap = right_part["_ts"].min() - left_part["_ts"].max()
        if gap < purge_delta:
            return False
    return True
