"""Phase 9.8 — walk-forward window definitions and partitioning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

STANDARD_EXPANDING_WINDOWS: tuple[tuple[tuple[int, int], tuple[int, int]], ...] = (
    ((2021, 2021), (2022, 2022)),
    ((2021, 2022), (2023, 2023)),
    ((2021, 2023), (2024, 2024)),
    ((2021, 2024), (2025, 2025)),
    ((2021, 2025), (2026, 2026)),
)

MIN_TRAIN_ROWS = 25
MIN_VALIDATION_ROWS = 10


@dataclass
class WalkForwardWindow:
    window_id: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    train_years: tuple[int, int]
    validation_years: tuple[int, int]
    mode: str = "expanding"

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "mode": self.mode,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "train_years": list(self.train_years),
            "validation_years": list(self.validation_years),
        }


def _year_mask(ts: pd.Series, start: int, end: int) -> pd.Series:
    years = pd.to_datetime(ts, utc=True).dt.year
    return (years >= start) & (years <= end)


def _iso_bounds(df: pd.DataFrame, mask: pd.Series) -> tuple[str, str]:
    if not mask.any():
        return "", ""
    subset = pd.to_datetime(df.loc[mask, "timestamp"], utc=True)
    return subset.min().isoformat(), subset.max().isoformat()


def build_standard_windows(df: pd.DataFrame) -> list[WalkForwardWindow]:
    """Build expanding year-based windows; adapt when standard years are absent."""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    years = sorted(ts.dt.year.unique().tolist())
    windows: list[WalkForwardWindow] = []

    if years and min(years) <= 2021 and max(years) >= 2022:
        for idx, (train_years, val_years) in enumerate(STANDARD_EXPANDING_WINDOWS, start=1):
            tr_s, tr_e = train_years
            va_s, va_e = val_years
            if va_e > max(years):
                continue
            if tr_s < min(years):
                continue
            train_mask = _year_mask(df["timestamp"], tr_s, tr_e)
            val_mask = _year_mask(df["timestamp"], va_s, va_e)
            if train_mask.sum() < MIN_TRAIN_ROWS or val_mask.sum() < MIN_VALIDATION_ROWS:
                continue
            tr_start, tr_end = _iso_bounds(df, train_mask)
            va_start, va_end = _iso_bounds(df, val_mask)
            windows.append(
                WalkForwardWindow(
                    window_id=f"window_{idx}",
                    train_start=tr_start,
                    train_end=tr_end,
                    validation_start=va_start,
                    validation_end=va_end,
                    train_years=train_years,
                    validation_years=val_years,
                    mode="expanding",
                )
            )

    if len(windows) < 4 and len(years) >= 3:
        windows = []
        for i in range(1, len(years)):
            tr_years = (years[0], years[i - 1])
            va_years = (years[i], years[i])
            train_mask = _year_mask(df["timestamp"], tr_years[0], tr_years[1])
            val_mask = _year_mask(df["timestamp"], va_years[0], va_years[1])
            if train_mask.sum() < MIN_TRAIN_ROWS or val_mask.sum() < MIN_VALIDATION_ROWS:
                continue
            tr_start, tr_end = _iso_bounds(df, train_mask)
            va_start, va_end = _iso_bounds(df, val_mask)
            windows.append(
                WalkForwardWindow(
                    window_id=f"window_adaptive_{i}",
                    train_start=tr_start,
                    train_end=tr_end,
                    validation_start=va_start,
                    validation_end=va_end,
                    train_years=tr_years,
                    validation_years=va_years,
                    mode="adaptive_expanding",
                )
            )

    if len(windows) < 4 and len(df) >= MIN_TRAIN_ROWS + MIN_VALIDATION_ROWS:
        windows = build_rolling_index_windows(df, n_windows=max(4, min(5, len(years) - 1)))

    return windows


def build_rolling_index_windows(df: pd.DataFrame, *, n_windows: int = 4) -> list[WalkForwardWindow]:
    """Rolling chronological index windows when year coverage is insufficient."""
    ordered = df.sort_values("timestamp").reset_index(drop=True)
    n = len(ordered)
    windows: list[WalkForwardWindow] = []
    step = max(1, (n - MIN_TRAIN_ROWS - MIN_VALIDATION_ROWS) // max(1, n_windows - 1))
    for i in range(n_windows):
        val_end = n - (n_windows - 1 - i) * step
        val_start = max(MIN_TRAIN_ROWS, val_end - step)
        train_end = val_start
        if train_end < MIN_TRAIN_ROWS or (val_end - val_start) < MIN_VALIDATION_ROWS:
            continue
        train_df = ordered.iloc[:train_end]
        val_df = ordered.iloc[val_start:val_end]
        windows.append(
            WalkForwardWindow(
                window_id=f"window_roll_{i + 1}",
                train_start=pd.Timestamp(train_df["timestamp"].iloc[0]).isoformat(),
                train_end=pd.Timestamp(train_df["timestamp"].iloc[-1]).isoformat(),
                validation_start=pd.Timestamp(val_df["timestamp"].iloc[0]).isoformat(),
                validation_end=pd.Timestamp(val_df["timestamp"].iloc[-1]).isoformat(),
                train_years=(0, 0),
                validation_years=(0, 0),
                mode="rolling",
            )
        )
    return windows


def partition_window(
    df: pd.DataFrame,
    window: WalkForwardWindow,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split dataframe into train and validation without overlap."""
    ordered = df.sort_values("timestamp").reset_index(drop=True)
    if window.mode == "rolling":
        train_end_ts = pd.Timestamp(window.train_end)
        val_start_ts = pd.Timestamp(window.validation_start)
        val_end_ts = pd.Timestamp(window.validation_end)
        train = ordered[pd.to_datetime(ordered["timestamp"], utc=True) <= train_end_ts]
        val = ordered[
            (pd.to_datetime(ordered["timestamp"], utc=True) >= val_start_ts)
            & (pd.to_datetime(ordered["timestamp"], utc=True) <= val_end_ts)
        ]
    else:
        tr_s, tr_e = window.train_years
        va_s, va_e = window.validation_years
        train = ordered.loc[_year_mask(ordered["timestamp"], tr_s, tr_e)]
        val = ordered.loc[_year_mask(ordered["timestamp"], va_s, va_e)]
    train = train.sort_values("timestamp").reset_index(drop=True)
    val = val.sort_values("timestamp").reset_index(drop=True)
    return train, val


def assert_no_overlap(train: pd.DataFrame, validation: pd.DataFrame) -> None:
    if train.empty or validation.empty:
        return
    train_max = pd.to_datetime(train["timestamp"], utc=True).max()
    val_min = pd.to_datetime(validation["timestamp"], utc=True).min()
    if val_min <= train_max:
        raise ValueError("Train/validation temporal overlap detected")


def assert_chronological(df: pd.DataFrame) -> None:
    ts = pd.to_datetime(df["timestamp"], utc=True)
    if not ts.is_monotonic_increasing:
        raise ValueError("Dataframe is not chronologically ordered")
