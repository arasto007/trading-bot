"""Phase 15I — router balance audit."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID, TREND_MODEL_ID
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame


def audit_router_balance(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    stride: int = 15,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get(RANGE_MODEL_ID), "inner", None)
    trend_inner = getattr(registry.get(TREND_MODEL_ID), "inner", None)

    selected_counts: dict[str, int] = {RANGE_MODEL_ID: 0, TREND_MODEL_ID: 0, "BLOCKED": 0}
    skipped_range = 0
    blocked_regime = 0
    range_actionable = 0
    trend_actionable = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        engine_id = select_engine(ctx.regime)
        if engine_id is None:
            selected_counts["BLOCKED"] += 1
            blocked_regime += 1
            continue
        selected_counts[engine_id] = selected_counts.get(engine_id, 0) + 1
        sig = select_signal(ctx, engine_id)
        if sig is None:
            continue
        if engine_id == RANGE_MODEL_ID:
            if ctx.regime != "RANGE":
                skipped_range += 1
            if sig.signal in ("BUY", "SELL"):
                range_actionable += 1
        elif engine_id == TREND_MODEL_ID and sig.signal in ("BUY", "SELL"):
            trend_actionable += 1

    total = sum(selected_counts.values()) or 1
    return {
        "phase": "15I",
        "engine_selection": selected_counts,
        "selection_pct": {k: round(v / total, 4) for k, v in selected_counts.items()},
        "range_actionable_raw": range_actionable,
        "trend_actionable_raw": trend_actionable,
        "blocked_regime_count": blocked_regime,
        "range_skipped_mismatch": skipped_range,
        "router_calls_phase9_9_correctly": skipped_range == 0,
        "balanced": range_actionable > 0 and trend_actionable > 0,
    }
