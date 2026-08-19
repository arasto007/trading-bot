"""Phase 13.4 — ML feature matrix from Phase 13.3 trend features (research only)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingbot.ml.research.trend_strategy.trend_features import TREND_FEATURE_COLUMNS, compute_trend_features

TREND_ML_EXTRA_COLUMNS: tuple[str, ...] = ("candle_momentum",)

TREND_ML_FEATURE_COLUMNS: tuple[str, ...] = (
    "ema20_slope",
    "ema50_slope",
    "ema_alignment",
    "adx",
    "atr_percentile",
    "rsi",
    "macd_histogram",
    "breakout_distance",
    "higher_high_count",
    "lower_low_count",
    "candle_momentum",
)


def _candle_momentum(close: pd.Series, atr: pd.Series, lookback: int = 5) -> pd.Series:
    mom = close.diff(lookback)
    return (mom / atr.replace(0, np.nan)).fillna(0.0)


def build_ml_features(
    candles: pd.DataFrame,
    *,
    _normalized: pd.DataFrame | None = None,
    _true_range: pd.Series | None = None,
) -> pd.DataFrame:
    """Load Phase 13.3 features and append candle momentum."""
    frame = compute_trend_features(candles, _normalized=_normalized, _true_range=_true_range)
    atr = frame["atr"].astype(float)
    frame["candle_momentum"] = _candle_momentum(frame["close"].astype(float), atr)
    return frame


def feature_matrix(samples: pd.DataFrame) -> pd.DataFrame:
    """Extract ML input columns from labeled signal samples."""
    cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in samples.columns]
    return samples[cols].astype(np.float64)
