"""Volatility feature family — range expansion and ATR state."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.market_filters import atr_percentile
from tradingbot.ml.features.base import FeatureDefinition, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "volatility"
_SOURCE = "candles"

_DEFINITIONS = [
    FeatureDefinition("atr_14", _SOURCE, "ATR(14) absolute value", "1.0", _FAMILY),
    FeatureDefinition("atr_percentile", _SOURCE, "ATR normalized by rolling volatility percentile", "1.0", _FAMILY),
    FeatureDefinition("realized_vol_20", _SOURCE, "20-bar realized volatility of returns", "1.0", _FAMILY),
    FeatureDefinition("range_pct", _SOURCE, "Current bar range as percent of close", "1.0", _FAMILY),
    FeatureDefinition("volatility_regime", _SOURCE, "0 low / 0.5 mid / 1 high vol bucket", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)


class VolatilityFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        if work is None or len(work) < 15:
            return {d.name: 0.0 for d in _DEFINITIONS}

        h, l, c = work["high"], work["low"], work["close"]
        tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14, min_periods=14).mean()
        atr_val = safe_float(atr.iloc[-1], 0.0)

        atr_pct = atr_percentile(work)
        rets = c.pct_change().dropna()
        realized = 0.0
        if len(rets) >= 5:
            realized = safe_float(rets.tail(min(20, len(rets))).std() * 100, 0.0)

        row = work.iloc[-1]
        rng_pct = safe_float((row["high"] - row["low"]) / max(row["close"], 1e-9) * 100, 0.0)

        regime = 0.5
        if atr_pct < 30:
            regime = 0.0
        elif atr_pct > 70:
            regime = 1.0

        return {
            "atr_14": round(atr_val, 6),
            "atr_percentile": round(atr_pct, 4),
            "realized_vol_20": round(realized, 6),
            "range_pct": round(rng_pct, 4),
            "volatility_regime": regime,
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return VolatilityFeatures().compute_features(df, index, **kwargs)
