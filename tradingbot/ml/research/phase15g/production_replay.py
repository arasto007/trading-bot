"""Phase 15G — production pipeline replay statistics."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase15g.bundle_statistics import distribution_stats


def replay_production_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    stride: int = 10,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get("phase9_9"), "inner", None)
    trend_inner = getattr(registry.get("trend_rf_v40"), "inner", None)

    counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    cal_conf: list[float] = []
    risk_blocked = 0
    cal_actionable = 0
    risk_pass_actionable = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        cal, risk, quality = stack.quality.evaluate(ctx)
        cal_conf.append(float(cal.final_confidence))
        counts[cal.final_action] = counts.get(cal.final_action, 0) + 1
        if cal.final_action in ("BUY", "SELL"):
            cal_actionable += 1
            if risk.allowed and quality.allowed:
                risk_pass_actionable += 1
            else:
                risk_blocked += 1

    return {
        "phase": "15G",
        "bars_evaluated": len(cal_conf),
        "direction_counts": counts,
        "calibration_actionable": cal_actionable,
        "risk_quality_pass": risk_pass_actionable,
        "risk_or_quality_blocked": risk_blocked,
        "calibrated_confidence": distribution_stats(cal_conf),
        "calibration_type": type(stack.calibration).__name__,
    }
