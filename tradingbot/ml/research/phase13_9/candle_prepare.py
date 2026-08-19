"""Shared candle normalization for unified frame build (Phase 24G)."""

from __future__ import annotations

import pandas as pd


def normalize_candles_index(candles: pd.DataFrame) -> pd.DataFrame:
    """Normalize candles to UTC DatetimeIndex — identical to trend/regime _normalize."""
    out = candles.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "time" in out.columns:
            out = out.set_index("time")
        elif "timestamp" in out.columns:
            out = out.set_index("timestamp")
    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


def true_range_series(df: pd.DataFrame) -> pd.Series:
    """True range series — identical formula used in trend/regime ATR paths."""
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    return pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
