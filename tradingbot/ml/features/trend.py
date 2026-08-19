"""Trend feature family — market state directional bias."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.market_filters import compute_adx
from tradingbot.ml.features.base import FeatureDefinition, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "trend"
_SOURCE = "candles"

_DEFINITIONS = [
    FeatureDefinition("ema50_slope", _SOURCE, "Normalized EMA50 slope over 5 bars", "1.0", _FAMILY),
    FeatureDefinition("ema200_distance", _SOURCE, "Close distance from EMA200 in ATR units", "1.0", _FAMILY),
    FeatureDefinition("price_above_ema200", _SOURCE, "1 if close above EMA200 else 0", "1.0", _FAMILY),
    FeatureDefinition("trend_strength", _SOURCE, "ADX trend strength 0-100", "1.0", _FAMILY),
    FeatureDefinition("ema_cross_state", _SOURCE, "1 bull EMA50>EMA200, -1 bear, 0 neutral", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


class TrendFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        if work is None or len(work) < 30:
            return {d.name: 0.0 for d in _DEFINITIONS}

        close = work["close"].astype(float)
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        atr = _atr_series(work)
        atr_val = safe_float(atr.iloc[-1], 1.0)

        slope = 0.0
        if len(ema50) >= 6:
            slope = safe_float((ema50.iloc[-1] - ema50.iloc[-6]) / max(atr_val, 1e-9), 0.0)

        ema200_dist = safe_float((close.iloc[-1] - ema200.iloc[-1]) / max(atr_val, 1e-9), 0.0)
        above_200 = 1.0 if close.iloc[-1] > ema200.iloc[-1] else 0.0
        adx = compute_adx(work)
        cross = 0.0
        if ema50.iloc[-1] > ema200.iloc[-1]:
            cross = 1.0
        elif ema50.iloc[-1] < ema200.iloc[-1]:
            cross = -1.0

        return {
            "ema50_slope": round(slope, 6),
            "ema200_distance": round(ema200_dist, 6),
            "price_above_ema200": above_200,
            "trend_strength": round(adx, 4),
            "ema_cross_state": cross,
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return TrendFeatures().compute_features(df, index, **kwargs)
