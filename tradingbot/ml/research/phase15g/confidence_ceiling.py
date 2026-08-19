"""Phase 15G — confidence ceiling proof for frozen bundle."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.calibration_adapter import load_recovered_calibration
from tradingbot.ml.research.phase15g.config import RISK_GATE_THRESHOLD
from tradingbot.ml.risk_intelligence.risk_policy import MIN_CONFIDENCE_FOR_RISK


def measure_confidence_ceiling(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
    stride: int = 5,
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
    orchestrator = DecisionOrchestrator()

    max_calibrated = 0.0
    max_raw = 0.0
    max_model_prob = 0.0
    max_bar: dict[str, Any] = {}
    calibrated_values: list[float] = []
    actionable_cal: list[float] = []

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_inner, trend_engine=trend_inner,
        )
        cal, _, _ = stack.quality.evaluate(ctx)
        cv = float(cal.final_confidence)
        rv = float(cal.raw_confidence.raw_value)
        mp = float(cal.raw_confidence.model_probability)
        calibrated_values.append(cv)
        if cal.final_action in ("BUY", "SELL"):
            actionable_cal.append(cv)
        if cv > max_calibrated:
            max_calibrated = cv
            max_raw = rv
            max_model_prob = mp
            max_bar = {
                "timestamp": str(row.get("timestamp", "")),
                "raw_confidence": round(rv, 6),
                "model_probability": round(mp, 6),
                "calibrated_confidence": round(cv, 6),
                "engine_signal": str(cal.raw_confidence.engine_signal),
                "final_action": cal.final_action,
                "regime": ctx.regime,
            }

    risk_threshold = float(MIN_CONFIDENCE_FOR_RISK)
    ceiling_below_risk = max_calibrated < risk_threshold
    gap = round(risk_threshold - max_calibrated, 6)

    return {
        "phase": "15G",
        "risk_gate_requirement": risk_threshold,
        "maximum_calibrated_confidence": round(max_calibrated, 6),
        "maximum_raw_confidence": round(max_raw, 6),
        "maximum_model_probability": round(max_model_prob, 6),
        "peak_bar": max_bar,
        "bars_scanned": len(calibrated_values),
        "actionable_calibration_count": len(actionable_cal),
        "actionable_calibrated_max": round(max(actionable_cal), 6) if actionable_cal else 0.0,
        "ceiling_below_risk_gate": ceiling_below_risk,
        "gap_to_risk_gate": gap if ceiling_below_risk else 0.0,
        "mathematical_proof": (
            f"max(calibrated)={max_calibrated:.6f} < MIN_CONFIDENCE_FOR_RISK={risk_threshold}"
            if ceiling_below_risk
            else f"max(calibrated)={max_calibrated:.6f} >= {risk_threshold}"
        ),
        "conclusion": (
            "Frozen bundle + Platt cannot reach RiskGate threshold"
            if ceiling_below_risk
            else "Frozen bundle can reach RiskGate threshold on at least one bar"
        ),
    }
