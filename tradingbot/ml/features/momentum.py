"""Momentum feature family — rate of change and oscillator state."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.features.base import FeatureDefinition, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "momentum"
_SOURCE = "candles"

_DEFINITIONS = [
    FeatureDefinition("rsi_14", _SOURCE, "RSI(14) normalized 0-100", "1.0", _FAMILY),
    FeatureDefinition("roc_10", _SOURCE, "10-bar rate of change percent", "1.0", _FAMILY),
    FeatureDefinition("macd_histogram", _SOURCE, "MACD histogram normalized by ATR", "1.0", _FAMILY),
    FeatureDefinition("momentum_5", _SOURCE, "5-bar close momentum in ATR units", "1.0", _FAMILY),
    FeatureDefinition("stoch_k", _SOURCE, "Stochastic %K 14-period", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)


def _rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    return safe_float(rsi.iloc[-1], 50.0)


def _atr_val(df: pd.DataFrame) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    return safe_float(atr.iloc[-1], 1.0)


class MomentumFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        if work is None or len(work) < 20:
            return {d.name: 0.0 for d in _DEFINITIONS}

        close = work["close"].astype(float)
        atr = _atr_val(work)
        rsi = _rsi(close)

        roc = 0.0
        if len(close) >= 11:
            prev = close.iloc[-11]
            if prev != 0:
                roc = safe_float((close.iloc[-1] / prev - 1) * 100, 0.0)

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = safe_float((macd.iloc[-1] - signal.iloc[-1]) / max(atr, 1e-9), 0.0)

        mom5 = 0.0
        if len(close) >= 6:
            mom5 = safe_float((close.iloc[-1] - close.iloc[-6]) / max(atr, 1e-9), 0.0)

        stoch = 50.0
        if len(work) >= 14:
            low14 = work["low"].tail(14).min()
            high14 = work["high"].tail(14).max()
            if high14 > low14:
                stoch = safe_float((close.iloc[-1] - low14) / (high14 - low14) * 100, 50.0)

        return {
            "rsi_14": round(rsi, 4),
            "roc_10": round(roc, 4),
            "macd_histogram": round(hist, 6),
            "momentum_5": round(mom5, 6),
            "stoch_k": round(stoch, 4),
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return MomentumFeatures().compute_features(df, index, **kwargs)
