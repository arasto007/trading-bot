"""Price action feature family — candle morphology and pattern state."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.price_action import _engulfing, _pin_bar
from tradingbot.ml.features.base import FeatureDefinition, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "price_action"
_SOURCE = "candles"

_DEFINITIONS = [
    FeatureDefinition("body_ratio", _SOURCE, "Candle body / total range", "1.0", _FAMILY),
    FeatureDefinition("upper_wick_ratio", _SOURCE, "Upper wick / total range", "1.0", _FAMILY),
    FeatureDefinition("lower_wick_ratio", _SOURCE, "Lower wick / total range", "1.0", _FAMILY),
    FeatureDefinition("engulfing_flag", _SOURCE, "1 bullish engulf, -1 bearish, 0 none", "1.0", _FAMILY),
    FeatureDefinition("pin_bar_flag", _SOURCE, "1 bull pin, -1 bear pin, 0 none", "1.0", _FAMILY),
    FeatureDefinition("candle_direction", _SOURCE, "1 bullish close, -1 bearish close", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)


class PriceActionFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        if work is None or work.empty:
            return {d.name: 0.0 for d in _DEFINITIONS}

        row = work.iloc[-1]
        rng = max(float(row["high"] - row["low"]), 1e-9)
        body = abs(float(row["close"] - row["open"]))
        upper = float(row["high"] - max(row["open"], row["close"]))
        lower = float(min(row["open"], row["close"]) - row["low"])

        engulf = _engulfing(work, len(work) - 1)
        pin = 0.0
        if _pin_bar(row, 1):
            pin = 1.0
        elif _pin_bar(row, -1):
            pin = -1.0

        direction = 1.0 if row["close"] >= row["open"] else -1.0

        return {
            "body_ratio": round(body / rng, 4),
            "upper_wick_ratio": round(upper / rng, 4),
            "lower_wick_ratio": round(lower / rng, 4),
            "engulfing_flag": float(engulf or 0),
            "pin_bar_flag": pin,
            "candle_direction": direction,
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return PriceActionFeatures().compute_features(df, index, **kwargs)
