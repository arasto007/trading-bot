"""SMC structure feature family — BOS, CHoCH, sweep, FVG, OB, premium/discount."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.price_action import (
    _liquidity_sweep,
    enrich_price_action,
    price_zone,
)
from tradingbot.ml.features.base import FeatureDefinition, normalize_atr_distance, safe_float, truncated_df
from tradingbot.ml.features.registry.registry import register_many

_FAMILY = "smc_structure"
_SOURCE = "candles + PA domain"

_DEFINITIONS = [
    FeatureDefinition("bos_state", _SOURCE, "1 if last structure break was BOS in break direction", "1.0", _FAMILY),
    FeatureDefinition("choch_state", _SOURCE, "1 if last structure break was CHoCH in break direction", "1.0", _FAMILY),
    FeatureDefinition("liquidity_sweep", _SOURCE, "1 bullish sweep, -1 bearish, 0 none at bar", "1.0", _FAMILY),
    FeatureDefinition("fvg_presence", _SOURCE, "1 if price inside unfilled FVG, signed by direction", "1.0", _FAMILY),
    FeatureDefinition("order_block_distance", _SOURCE, "ATR-normalized distance to nearest order block", "1.0", _FAMILY),
    FeatureDefinition("premium_discount_location", _SOURCE, "-1 discount, 0 equilibrium, 1 premium", "1.0", _FAMILY),
    FeatureDefinition("structure_distance", _SOURCE, "Bars since last BOS/CHoCH break", "1.0", _FAMILY),
]
register_many(_DEFINITIONS)

_ZONE_MAP = {"discount": -1.0, "equilibrium": 0.0, "premium": 1.0}


def _pa_context(df: pd.DataFrame, index: int, pa_cfg: dict[str, Any] | None) -> tuple:
    work = truncated_df(df, index)
    cfg = pa_cfg or {}
    enriched = enrich_price_action(work, cfg, at_index=len(work) - 1)
    swings = enriched.attrs.get("pa_swings") or []
    breaks = enriched.attrs.get("pa_breaks") or []
    fvgs = enriched.attrs.get("pa_fvgs") or []
    obs = enriched.attrs.get("pa_obs") or []
    atr = enriched["atr"].iloc[-1] if "atr" in enriched.columns else work["close"].iloc[-1] * 0.001
    return work, enriched, swings, breaks, fvgs, obs, safe_float(atr, 1.0)


class SmcStructureFeatures:
    family_name = _FAMILY

    def feature_definitions(self) -> list[FeatureDefinition]:
        return list(_DEFINITIONS)

    def compute_features(self, df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
        pa_cfg = kwargs.get("pa_cfg")
        work, enriched, swings, breaks, fvgs, obs, atr = _pa_context(df, index, pa_cfg)
        if work is None or len(work) < 30:
            return {d.name: 0.0 for d in _DEFINITIONS}

        i = len(work) - 1
        price = float(work["close"].iloc[i])

        bos_state = 0.0
        choch_state = 0.0
        structure_distance = 999.0
        if breaks:
            last = breaks[-1]
            structure_distance = float(i - last.index)
            if last.kind == "bos":
                bos_state = float(last.direction)
            elif last.kind == "choch":
                choch_state = float(last.direction)

        sweep = _liquidity_sweep(work, swings, i)
        liquidity_sweep = float(sweep or 0)

        fvg_presence = 0.0
        for gap in reversed(fvgs):
            if gap.index > i or gap.filled:
                continue
            if gap.bottom <= price <= gap.top:
                fvg_presence = float(gap.direction)
                break

        ob_distance = 0.0
        best_dist = None
        for ob in reversed(obs):
            if ob.index > i:
                continue
            mid = (ob.top + ob.bottom) / 2.0
            dist = abs(normalize_atr_distance(price, mid, atr))
            if best_dist is None or dist < best_dist:
                best_dist = dist
                ob_distance = normalize_atr_distance(price, mid, atr)
        if best_dist is None:
            ob_distance = 0.0

        zone = price_zone(work, i)
        premium_discount = _ZONE_MAP.get(zone, 0.0)

        return {
            "bos_state": bos_state,
            "choch_state": choch_state,
            "liquidity_sweep": liquidity_sweep,
            "fvg_presence": fvg_presence,
            "order_block_distance": round(ob_distance, 6),
            "premium_discount_location": premium_discount,
            "structure_distance": min(structure_distance, 999.0),
        }


def compute_features(df: pd.DataFrame, index: int, **kwargs: Any) -> dict[str, float]:
    return SmcStructureFeatures().compute_features(df, index, **kwargs)
