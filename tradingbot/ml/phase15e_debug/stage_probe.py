"""Phase 15E — per-bar stage probe through ML pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.factory import MLKernelStack


@dataclass
class StageProbeResult:
    timestamp: str
    unified_ok: bool = False
    regime: str = ""
    range_signal: str = "HOLD"
    trend_signal: str = "HOLD"
    range_confidence: float = 0.0
    trend_confidence: float = 0.0
    engine_raw_signal: str = "HOLD"
    engine_raw_confidence: float = 0.0
    policy_rejection: str = ""
    decision_14_1_action: str = "HOLD"
    decision_14_1_confidence: float = 0.0
    calibrated_action: str = "HOLD"
    calibrated_confidence: float = 0.0
    raw_confidence: float = 0.0
    risk_allowed: bool = False
    risk_percent: float = 0.0
    risk_blocked_by: str | None = None
    quality_allowed: bool = False
    quality_score: float = 0.0
    quality_blocked_by: str | None = None
    kernel_final_action: str = "HOLD"
    trading_signal: str | None = None
    legacy_signal: str | None = None
    drop_stage: str = ""
    drop_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "unified_ok": self.unified_ok,
            "regime": self.regime,
            "range_signal": self.range_signal,
            "trend_signal": self.trend_signal,
            "range_confidence": round(self.range_confidence, 6),
            "trend_confidence": round(self.trend_confidence, 6),
            "engine_raw_signal": self.engine_raw_signal,
            "engine_raw_confidence": round(self.engine_raw_confidence, 6),
            "policy_rejection": self.policy_rejection,
            "decision_14_1_action": self.decision_14_1_action,
            "decision_14_1_confidence": round(self.decision_14_1_confidence, 6),
            "calibrated_action": self.calibrated_action,
            "calibrated_confidence": round(self.calibrated_confidence, 6),
            "raw_confidence": round(self.raw_confidence, 6),
            "risk_allowed": self.risk_allowed,
            "risk_percent": round(self.risk_percent, 6),
            "risk_blocked_by": self.risk_blocked_by,
            "quality_allowed": self.quality_allowed,
            "quality_score": round(self.quality_score, 6),
            "quality_blocked_by": self.quality_blocked_by,
            "kernel_final_action": self.kernel_final_action,
            "trading_signal": self.trading_signal,
            "legacy_signal": self.legacy_signal,
            "drop_stage": self.drop_stage,
            "drop_reason": self.drop_reason,
            "error": self.error,
        }


def _engine_inners(adapter: KernelAdapter) -> tuple[Any, Any]:
    deps = adapter._deps  # noqa: SLF001 — read-only diagnostic access
    range_eng = deps.registry.get("phase9_9")
    trend_eng = deps.registry.get("trend_rf_v40")
    if range_eng is None or trend_eng is None:
        raise ValueError("registry_engines_missing")
    range_inner = getattr(range_eng, "inner", None)
    trend_inner = getattr(trend_eng, "inner", None)
    if range_inner is None or trend_inner is None:
        raise ValueError("engine_inner_missing")
    return range_inner, trend_inner


def _assign_drop(result: StageProbeResult, stage: str, reason: str) -> None:
    if not result.drop_stage:
        result.drop_stage = stage
        result.drop_reason = reason


def probe_bar(
    *,
    market: MarketKey,
    slice_df: pd.DataFrame,
    stack: MLKernelStack,
    adapter: KernelAdapter,
    legacy_signal: TradingSignal | None = None,
    config: dict[str, Any] | None = None,
    base_dir: str | None = None,
) -> StageProbeResult:
    ts = str(slice_df.index[-1])
    result = StageProbeResult(timestamp=ts)
    if legacy_signal is not None:
        result.legacy_signal = getattr(getattr(legacy_signal, "direction", None), "name", None)

    try:
        unified = PipelineCache.get_unified_frame(
            slice_df,
            base_dir=base_dir,
            symbol=market.symbol,
            timeframe=market.timeframe,
        )
        if unified.empty:
            result.error = "unified_frame_empty"
            _assign_drop(result, "unified_features", "unified frame empty")
            return result
        result.unified_ok = True

        row = unified.iloc[-1]
        range_inner, trend_inner = _engine_inners(adapter)
        ctx = build_market_context(
            row,
            symbol=market.symbol,
            timeframe=market.timeframe,
            range_engine=range_inner,
            trend_engine=trend_inner,
        )
        result.regime = ctx.regime
        result.range_signal = ctx.range_signal.signal
        result.trend_signal = ctx.trend_signal.signal
        result.range_confidence = float(ctx.range_signal.confidence)
        result.trend_confidence = float(ctx.trend_signal.confidence)

        engine_id = select_engine(ctx.regime)
        selected = select_signal(ctx, engine_id)
        if selected is not None:
            result.engine_raw_signal = selected.signal
            result.engine_raw_confidence = float(selected.confidence)

        decision = stack.orchestrator.decide(ctx)
        result.decision_14_1_action = decision.action
        result.decision_14_1_confidence = float(decision.confidence)

        if decision.action not in ("BUY", "SELL"):
            if result.engine_raw_signal in ("BUY", "SELL"):
                result.policy_rejection = stack.orchestrator.policy.rejection_reason(
                    result.engine_raw_confidence,
                ) or "confidence_gate"
            _assign_drop(result, "decision_14_1", "; ".join(decision.explanation[:2]) or "HOLD")

        calibrated = stack.calibration.decide(ctx)
        result.calibrated_action = calibrated.final_action
        result.calibrated_confidence = float(calibrated.final_confidence)
        result.raw_confidence = float(calibrated.raw_confidence.raw_value)

        if calibrated.final_action not in ("BUY", "SELL") and decision.action in ("BUY", "SELL"):
            _assign_drop(result, "calibration_14_2a", "calibration gate blocked signal")
        elif calibrated.final_action not in ("BUY", "SELL") and not result.drop_stage:
            _assign_drop(result, "calibration_14_2a", "calibrated HOLD")

        _cal, risk = stack.risk.evaluate(ctx)
        result.risk_allowed = bool(risk.allowed)
        result.risk_percent = float(risk.risk_percent)
        result.risk_blocked_by = risk.blocked_by

        if calibrated.final_action in ("BUY", "SELL") and not risk.allowed:
            _assign_drop(result, "risk_14_2b", risk.reason or str(risk.blocked_by))

        _cal2, risk2, quality = stack.quality.evaluate(ctx)
        result.quality_allowed = bool(quality.allowed)
        result.quality_score = float(quality.score)
        result.quality_blocked_by = quality.blocked_by

        if calibrated.final_action in ("BUY", "SELL") and risk.allowed and not quality.allowed:
            _assign_drop(result, "quality_14_3", quality.reason or str(quality.blocked_by))

        action = str(calibrated.final_action)
        if action not in ("BUY", "SELL"):
            action = "HOLD"
        if not risk.allowed or not quality.allowed:
            action = "HOLD"
        result.kernel_final_action = action

        if calibrated.final_action in ("BUY", "SELL") and risk.allowed and quality.allowed and action == "HOLD":
            _assign_drop(result, "kernel_adapter", "adapter forced HOLD")

        trading = adapter.generate_signal(market, slice_df.copy(), config=config)
        if trading is not None:
            result.trading_signal = trading.direction.name
        elif action in ("BUY", "SELL"):
            _assign_drop(result, "signal_mapper", "mapper dropped actionable unified signal")
        elif result.legacy_signal in ("BUY", "SELL") and not result.drop_stage:
            _assign_drop(result, "ml_pipeline", "legacy active but ML produced no trade")

    except Exception as exc:
        result.error = str(exc)
        if not result.drop_stage:
            _assign_drop(result, "exception", str(exc))

    return result
