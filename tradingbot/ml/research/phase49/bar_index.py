"""Bar index resolution on fullest candle store (research only)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def resolve_bar_index(candles: pd.DataFrame, timestamp: pd.Timestamp | str) -> int:
    """Map event timestamp to absolute bar index on the full candle frame."""
    ts = pd.to_datetime(timestamp, utc=True)
    cidx = pd.to_datetime(candles.index, utc=True).astype(np.int64)
    tval = int(pd.to_datetime(ts, utc=True).value)
    return int(np.searchsorted(cidx.to_numpy(), tval, side="right") - 1)
