"""Higher timeframe context features — H4 bias, M15 state, M5 entry context."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.htf_bias import compute_htf_bias
from tradingbot.domain.price_action import Trend, enrich_price_action, infer_trend, price_zone
from tradingbot.ml.features.align import closed_htf_slice
from tradingbot.ml.features.base import FeatureDefinition, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "htf_context"
_SOURCE = "H4/M15/M5 aligned candles"

_DEFINITIONS = [
    FeatureDefinition("h4_trend_bias", _SOURCE, "H4 trend bias: 1 bull, -1 bear, 0 range", "1.0", _FAMILY),
    FeatureDefinition("h4_structure_direction", _SOURCE, "H4 last structure break direction", "1.0", _FAMILY),
    FeatureDefinition("m15_market_state", _SOURCE, "M15 encoded market state trend + structure", "1.0", _FAMILY),
    FeatureDefinition("m5_entry_context", _SOURCE, "M5 entry zone + sweep readiness score", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)

_TREND_CODE = {Trend.BULL: 1.0, Trend.BEAR: -1.0, Trend.RANGE: 0.0}
_ZONE_SCORE = {"discount": 1.0, "equilibrium": 0.5, "premium": 0.0}


class HtfContextFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        work = truncated_df(df, index)
        symbol = kwargs.get("symbol", "XAUUSD")
        h4_df: pd.DataFrame | None = kwargs.get("h4_df")
        m15_df: pd.DataFrame | None = kwargs.get("m15_df")
        entry_ts = work.index[-1] if work is not None and not work.empty else None

        h4_bias = 0.0
        h4_structure = 0.0
        if h4_df is not None and entry_ts is not None:
            h4_slice = closed_htf_slice(h4_df, entry_ts, "H4")
            if h4_slice is not None and len(h4_slice) >= 60:
                h4_cfg = get_price_action_config(symbol, "H4")
                h4_bias = float(compute_htf_bias(h4_slice, h4_cfg))
                enriched = enrich_price_action(h4_slice, h4_cfg, at_index=len(h4_slice) - 1)
                breaks = enriched.attrs.get("pa_breaks") or []
                if breaks:
                    h4_structure = float(breaks[-1].direction)

        m15_state = 0.0
        if m15_df is not None and entry_ts is not None:
            m15_slice = closed_htf_slice(m15_df, entry_ts, "M15")
            if m15_slice is not None and len(m15_slice) >= 40:
                m15_cfg = get_price_action_config(symbol, "M15")
                enriched = enrich_price_action(m15_slice, m15_cfg, at_index=len(m15_slice) - 1)
                trend = enriched.attrs.get("pa_trend", Trend.RANGE)
                breaks = enriched.attrs.get("pa_breaks") or []
                trend_part = _TREND_CODE.get(trend, 0.0)
                struct_part = float(breaks[-1].direction) if breaks else 0.0
                m15_state = round(trend_part * 0.6 + struct_part * 0.4, 4)

        m5_context = 0.0
        if work is not None and len(work) >= 20:
            m5_cfg = get_price_action_config(symbol, "M5")
            enriched = enrich_price_action(work, m5_cfg, at_index=len(work) - 1)
            swings = enriched.attrs.get("pa_swings") or []
            from tradingbot.domain.price_action import _liquidity_sweep, had_recent_sweep

            zone = price_zone(work, len(work) - 1)
            zone_score = _ZONE_SCORE.get(zone, 0.5)
            sweep_flag = 1.0 if had_recent_sweep(work, swings, len(work) - 1, bars=8) else 0.0
            sweep_now = _liquidity_sweep(work, swings, len(work) - 1)
            sweep_now_flag = 1.0 if sweep_now else 0.0
            m5_context = round(zone_score * 0.5 + sweep_flag * 0.3 + sweep_now_flag * 0.2, 4)

        return {
            "h4_trend_bias": h4_bias,
            "h4_structure_direction": h4_structure,
            "m15_market_state": m15_state,
            "m5_entry_context": m5_context,
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return HtfContextFeatures().compute_features(df, index, **kwargs)
