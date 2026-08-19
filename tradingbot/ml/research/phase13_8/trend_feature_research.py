"""Phase 13.8 — trend feature frame builder (Phase 13.3 canonical path)."""

from __future__ import annotations

import pandas as pd

from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_strategy.trend_features import compute_trend_features


def build_canonical_trend_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Full Phase 13.3 feature path with ML extras (candle_momentum)."""
    return build_ml_features(candles)


def build_phase133_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Exact Phase 13.3 feature extraction."""
    return compute_trend_features(candles)
