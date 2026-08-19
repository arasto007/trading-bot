"""Multi-timeframe alignment â€” causal higher-TF context for entry bars."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

_TF_BAR_DELTA: dict[str, pd.Timedelta] = {
    "M1": pd.Timedelta(minutes=1),
    "M5": pd.Timedelta(minutes=5),
    "M15": pd.Timedelta(minutes=15),
    "H1": pd.Timedelta(hours=1),
    "H4": pd.Timedelta(hours=4),
    "D1": pd.Timedelta(days=1),
}


def bar_close_time(ts: pd.Timestamp | datetime, timeframe: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    delta = _TF_BAR_DELTA.get(timeframe.upper(), pd.Timedelta(minutes=5))
    return ts + delta


def closed_htf_index(htf_df: pd.DataFrame, entry_ts: pd.Timestamp | datetime, timeframe: str) -> int | None:
    """
    Index of the last fully closed HTF bar at `entry_ts`.
    Uses bar open time + duration <= entry_ts (no look-ahead).
    """
    if htf_df is None or htf_df.empty:
        return None
    ts = pd.Timestamp(entry_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    delta = _TF_BAR_DELTA.get(timeframe.upper(), pd.Timedelta(hours=4))
    idx = htf_df.index
    if getattr(idx, 'tz', None) is None:
        idx = idx.tz_localize('UTC')
    else:
        idx = idx.tz_convert('UTC')
    close_times = idx + delta
    mask = np.asarray(close_times <= ts)
    if not mask.any():
        return None
    return int(mask.nonzero()[0][-1])


def closed_htf_slice(
    htf_df: pd.DataFrame,
    entry_ts: pd.Timestamp | datetime,
    timeframe: str,
) -> pd.DataFrame | None:
    """Truncated HTF dataframe containing only bars closed before entry_ts."""
    idx = closed_htf_index(htf_df, entry_ts, timeframe)
    if idx is None:
        return None
    return htf_df.iloc[: idx + 1]
