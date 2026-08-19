"""VOL_REGIME rule-only branch — shadow→production bridge (no ML filter)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import (
    VOL_REGIME_ENGINE_ID,
    VOL_REGIME_RULE_CONFIDENCE,
)
from tradingbot.ml.decision_engine.decision_types import Action, FinalDecision, MarketContext
from tradingbot.strategies.vol_regime_signal import (
    CONFIG_ID,
    DEFAULT_ATR_SL_MULT,
    DEFAULT_TP_RR,
    STRATEGY_ID,
    evaluate_at_index,
    prepare_frame,
)

RULE_CONFIDENCE = VOL_REGIME_RULE_CONFIDENCE


def _direction_to_action(direction: int) -> Action:
    return "BUY" if direction > 0 else "SELL"


def evaluate_vol_regime_from_frame(
    frame: pd.DataFrame,
    idx: int,
    *,
    symbol: str,
    timeframe: str,
    timestamp: datetime | None = None,
) -> FinalDecision | None:
    """Evaluate VOL_REGIME at bar index — rule-only, no ML."""
    sig = evaluate_at_index(frame, idx)
    if sig is None:
        return None
    ts = timestamp or pd.Timestamp(frame.index[idx]).to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    action = _direction_to_action(sig.direction)
    return FinalDecision(
        action=action,
        engine=VOL_REGIME_ENGINE_ID,
        confidence=RULE_CONFIDENCE,
        regime="TREND",
        timestamp=ts,
        explanation=[
            "vol_regime rule-only branch (ML SKIP)",
            f"config {CONFIG_ID}",
            f"ATR SL x{DEFAULT_ATR_SL_MULT}, TP RR {DEFAULT_TP_RR}",
        ],
        risk_hint=RULE_CONFIDENCE,
        trace=["vol_regime_branch: rule signal accepted"],
        metadata={
            "hypothesis_id": STRATEGY_ID,
            "config_id": CONFIG_ID,
            "engine_id": VOL_REGIME_ENGINE_ID,
            "atr_sl_mult": DEFAULT_ATR_SL_MULT,
            "tp_rr": DEFAULT_TP_RR,
            "ml_filter": "SKIP",
            "symbol": symbol,
            "timeframe": timeframe,
            "bar_index": idx,
            "atr_pct": sig.atr_pct,
            "research_only": False,
            "production_path": "shadow_production_bridge",
        },
    )


def try_vol_regime_from_features(context: MarketContext) -> FinalDecision | None:
    """
    Lightweight bridge when upstream populates features with vol_regime evaluation.

    Expected features keys (optional):
      vol_regime_direction: 1 | -1 | 0
      vol_regime_enabled: bool
    """
    features = context.features or {}
    if not features.get("vol_regime_enabled", True):
        return None
    direction = features.get("vol_regime_direction")
    if direction not in (1, -1):
        return None
    ts = context.timestamp or datetime.now(timezone.utc)
    action = _direction_to_action(int(direction))
    return FinalDecision(
        action=action,
        engine=VOL_REGIME_ENGINE_ID,
        confidence=RULE_CONFIDENCE,
        regime=context.regime,
        timestamp=ts,
        explanation=[
            "vol_regime rule-only branch (features bridge)",
            f"config {CONFIG_ID}",
        ],
        risk_hint=RULE_CONFIDENCE,
        trace=["vol_regime_branch: features bridge"],
        metadata={
            "hypothesis_id": STRATEGY_ID,
            "config_id": CONFIG_ID,
            "engine_id": VOL_REGIME_ENGINE_ID,
            "atr_sl_mult": float(features.get("vol_regime_atr_sl_mult", DEFAULT_ATR_SL_MULT)),
            "tp_rr": float(features.get("vol_regime_tp_rr", DEFAULT_TP_RR)),
            "ml_filter": "SKIP",
            "production_path": "features_bridge",
        },
    )


def enrich_features_from_candles(
    candles: pd.DataFrame,
    features: dict[str, Any],
    *,
    bar_index: int | None = None,
) -> dict[str, Any]:
    """Add vol_regime fields to market features for DecisionOrchestrator routing."""
    out = dict(features)
    if candles is None or candles.empty:
        out["vol_regime_direction"] = 0
        return out
    frame = prepare_frame(candles)
    idx = len(frame) - 1 if bar_index is None else bar_index
    sig = evaluate_at_index(frame, idx)
    out["vol_regime_direction"] = int(sig.direction) if sig is not None else 0
    out["vol_regime_enabled"] = True
    out["vol_regime_atr_sl_mult"] = DEFAULT_ATR_SL_MULT
    out["vol_regime_tp_rr"] = DEFAULT_TP_RR
    out["vol_regime_config_id"] = CONFIG_ID
    if sig is not None:
        out["vol_regime_atr_pct"] = sig.atr_pct
    return out
