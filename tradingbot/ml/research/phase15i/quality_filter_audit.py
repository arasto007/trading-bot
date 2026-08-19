"""Phase 15I — quality filter audit for RANGE regime."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def audit_quality_blocks(
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
    from tradingbot.ml.integration.factory import build_ml_kernel_stack

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_inner = getattr(registry.get("trend_rf_v40"), "inner", None)

    blocks: dict[str, int] = {}
    range_risk_passed = 0
    range_quality_blocked = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        if rule_classify_row(row) != "RANGE":
            continue
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        _cal, risk, quality = stack.quality.evaluate(ctx)
        if risk.allowed and _cal.final_action in ("BUY", "SELL"):
            range_risk_passed += 1
            if not quality.allowed:
                range_quality_blocked += 1
                key = str(quality.blocked_by or "unknown")
                blocks[key] = blocks.get(key, 0) + 1

    return {
        "phase": "15I",
        "regime": "RANGE",
        "risk_passed_actionable": range_risk_passed,
        "quality_blocked": range_quality_blocked,
        "quality_passed": range_risk_passed - range_quality_blocked,
        "blocked_by": blocks,
    }
