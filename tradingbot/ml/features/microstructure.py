"""Market microstructure features — spread and tick-derived state."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.features.base import FeatureDefinition, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "microstructure"
_SOURCE = "spread/tick data"

_DEFINITIONS = [
    FeatureDefinition("spread_pips", _SOURCE, "Bid-ask spread in pips at bar time", "1.0", _FAMILY),
    FeatureDefinition("spread_zscore", _SOURCE, "Spread z-score vs recent rolling window", "1.0", _FAMILY),
    FeatureDefinition("spread_spike", _SOURCE, "1 if spread z-score > 2 else 0", "1.0", _FAMILY),
    FeatureDefinition("tick_volume_proxy", _SOURCE, "Candle volume as liquidity proxy", "1.0", _FAMILY),
    FeatureDefinition("bar_spread_pct", _SOURCE, "High-low range relative to close (micro noise)", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)


class MicrostructureFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        spread_series: pd.Series | None = kwargs.get("spread_series")

        spread_pips = 0.0
        spread_z = 0.0
        spread_spike = 0.0

        if spread_series is not None and not spread_series.empty and work is not None and not work.empty:
            ts = work.index[-1]
            aligned = spread_series.loc[:ts]
            if not aligned.empty:
                spread_pips = safe_float(aligned.iloc[-1], 0.0)
                window = aligned.tail(min(60, len(aligned)))
                if len(window) >= 5:
                    mean = float(window.mean())
                    std = float(window.std())
                    if std > 0:
                        spread_z = (spread_pips - mean) / std
                        spread_spike = 1.0 if spread_z > 2.0 else 0.0

        tick_vol = 0.0
        bar_spread_pct = 0.0
        if work is not None and not work.empty:
            row = work.iloc[-1]
            if "volume" in work.columns:
                vol = work["volume"].astype(float)
                tick_vol = safe_float(vol.iloc[-1], 0.0)
                if len(vol) >= 20:
                    med = float(vol.tail(20).median())
                    if med > 0:
                        tick_vol = round(tick_vol / med, 4)
            bar_spread_pct = safe_float(
                (row["high"] - row["low"]) / max(row["close"], 1e-9) * 10000,
                0.0,
            )

        return {
            "spread_pips": round(spread_pips, 4),
            "spread_zscore": round(spread_z, 4),
            "spread_spike": spread_spike,
            "tick_volume_proxy": round(tick_vol, 4),
            "bar_spread_pct": round(bar_spread_pct, 4),
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return MicrostructureFeatures().compute_features(df, index, **kwargs)
