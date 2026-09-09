"""Phase 15F — full confidence stage trace for one bar."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey
from tradingbot.ml.confidence_engine.calibrator import ConfidenceCalibrator
from tradingbot.ml.confidence_engine.validator import CalibratedDecisionAdapter, raw_confidence_from_decision
from tradingbot.ml.decision_engine.decision_policy import DEFAULT_MIN_CONFIDENCE
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.signal_mapper import map_unified_to_trading_signal
from tradingbot.ml.phase15a.unified_signal import UnifiedSignal


def _engine_inners(adapter: Any) -> tuple[Any, Any]:
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    deps = adapter._deps
    range_eng = deps.registry.get("phase9_9")
    trend_eng = deps.registry.get(resolve_active_trend_engine_id())
    return getattr(range_eng, "inner", None), getattr(trend_eng, "inner", None)


def trace_confidence_flow(
    *,
    market: MarketKey,
    slice_df: pd.DataFrame,
    base_dir: str | None = None,
) -> dict[str, Any]:
    """Log every confidence value from prediction through TradingSignal."""
    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=market.symbol)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=market.symbol, stack=stack)

    unified = PipelineCache.get_unified_frame(
        slice_df, base_dir=base_dir, symbol=market.symbol, timeframe=market.timeframe,
    )
    if unified.empty:
        return {"error": "unified_frame_empty"}

    row = unified.iloc[-1]
    range_inner, trend_inner = _engine_inners(adapter)
    ctx = build_market_context(
        row, symbol=market.symbol, timeframe=market.timeframe,
        range_engine=range_inner, trend_engine=trend_inner,
    )

    engine_id = select_engine(ctx.regime)
    selected = select_signal(ctx, engine_id)
    engine_prob = float(selected.probability) if selected else 0.0
    engine_conf = float(selected.confidence) if selected else 0.0
    engine_signal = selected.signal if selected else "HOLD"

    decision = stack.orchestrator.decide(ctx)
    raw = raw_confidence_from_decision(decision, ctx)

    heuristic_cal = ConfidenceCalibrator().calibrate(raw)
    platt_calibrated, risk, quality = stack.quality.evaluate(ctx)

    try:
        unified_sig = adapter.produce_unified_signal(market, slice_df.copy())
        trading = map_unified_to_trading_signal(unified_sig, market, slice_df)
    except KernelFallbackError:
        unified_sig = type("U", (), {
            "direction": "HOLD", "confidence": float(platt_calibrated.final_confidence),
        })()
        trading = map_unified_to_trading_signal(
            UnifiedSignal(
                engine=platt_calibrated.decision.engine or "",
                regime=platt_calibrated.decision.regime,
                direction="HOLD",
                confidence=float(platt_calibrated.final_confidence),
                quality=float(quality.score),
                risk=float(risk.risk_percent),
                reason=[],
                trace=[],
            ),
            market,
            slice_df,
        )

    legacy_heuristic = CalibratedDecisionAdapter(stack.orchestrator, calibrator=ConfidenceCalibrator())
    legacy_cal = legacy_heuristic.decide(ctx)

    return {
        "timestamp": str(slice_df.index[-1]),
        "regime": ctx.regime,
        "stages": {
            "engine_probability": engine_prob,
            "engine_confidence": engine_conf,
            "engine_signal": engine_signal,
            "decision_raw_confidence": float(decision.confidence),
            "decision_action": decision.action,
            "decision_model_confidence": float(decision.metadata.get("model_confidence", 0)),
            "calibration_heuristic_value": float(heuristic_cal.calibrated_value),
            "calibration_platt_value": float(platt_calibrated.final_confidence),
            "calibration_platt_action": platt_calibrated.final_action,
            "calibration_legacy_heuristic_action": legacy_cal.final_action,
            "risk_allowed": bool(risk.allowed),
            "risk_percent": float(risk.risk_percent),
            "quality_allowed": bool(quality.allowed),
            "quality_score": float(quality.score),
            "unified_direction": unified_sig.direction,
            "unified_confidence": float(unified_sig.confidence),
            "trading_direction": trading.direction.name,
            "trading_confidence": float(trading.confidence),
        },
        "compression": {
            "engine_to_decision_ratio": (
                float(decision.confidence) / engine_conf if engine_conf > 0 else 0.0
            ),
            "decision_to_platt_ratio": (
                float(platt_calibrated.final_confidence) / float(decision.confidence)
                if decision.confidence > 0 else 0.0
            ),
            "unified_uses_calibrated": unified_sig.confidence == platt_calibrated.final_confidence,
        },
        "policy": {
            "min_confidence_14_1": DEFAULT_MIN_CONFIDENCE,
            "platt_threshold": float(getattr(stack.calibration.policy, "min_calibrated_confidence", 0)),
            "calibration_type": type(stack.calibration).__name__,
        },
        "diagnosis": {
            "compression_in": "decision_14_1_confidence_engine",
            "missing_platt_prior": legacy_cal.final_action == "HOLD" and platt_calibrated.final_action in ("BUY", "SELL"),
            "mapper_drops": (
                unified_sig.direction in ("BUY", "SELL")
                and trading.direction == SignalDirection.HOLD
            ),
        },
    }
