"""Phase 15J — per-bar TREND pipeline trace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import TREND_MODEL_ID
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.research.phase15j.config import TREND_ENGINE_ID, VALID_STOP_STAGES
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


@dataclass
class TrendTraceRecord:
    timestamp: str
    symbol: str
    regime: str
    selected_engine: str | None
    trend_probability: float
    trend_prediction: str
    raw_confidence: float
    compressed_confidence: float
    calibrated_confidence: float
    mapped_confidence: float | None
    risk_allowed: bool
    risk_reason: str | None
    quality_allowed: bool
    quality_reason: str | None
    kernel_signal: str
    final_signal: str
    stop_stage: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "regime": self.regime,
            "selected_engine": self.selected_engine,
            "trend_probability": round(self.trend_probability, 6),
            "trend_prediction": self.trend_prediction,
            "raw_confidence": round(self.raw_confidence, 6),
            "compressed_confidence": round(self.compressed_confidence, 6),
            "calibrated_confidence": round(self.calibrated_confidence, 6),
            "mapped_confidence": (
                round(self.mapped_confidence, 6) if self.mapped_confidence is not None else None
            ),
            "risk_allowed": self.risk_allowed,
            "risk_reason": self.risk_reason,
            "quality_allowed": self.quality_allowed,
            "quality_reason": self.quality_reason,
            "kernel_signal": self.kernel_signal,
            "final_signal": self.final_signal,
            "stop_stage": self.stop_stage,
        }


def _actionable(action: str) -> bool:
    return str(action).upper() in ("BUY", "SELL")


def _detect_stop_stage(
    *,
    engine_action: str,
    decision_action: str,
    calibrated_action: str,
    mapped_ok: bool,
    risk_allowed: bool,
    quality_allowed: bool,
    kernel_action: str,
    final_signal: str,
) -> str:
    if not _actionable(engine_action):
        return "ENGINE"
    if not _actionable(decision_action):
        return "DECISION"
    if not _actionable(calibrated_action):
        return "CALIBRATION"
    if not mapped_ok:
        return "MAPPING"
    if not risk_allowed:
        return "RISK"
    if not quality_allowed:
        return "QUALITY"
    if not _actionable(kernel_action):
        return "KERNEL"
    if _actionable(final_signal):
        return "NONE"
    return "KERNEL"


def trace_trend_bar(
    row: pd.Series,
    *,
    stack: Any,
    range_inner: Any,
    trend_inner: Any,
    bundle: Any,
    symbol: str,
    timeframe: str,
) -> TrendTraceRecord | None:
    regime = rule_classify_row(row)
    engine_id = select_engine(regime)
    if engine_id != TREND_ENGINE_ID or regime != "TREND":
        return None

    ts = str(row.get("timestamp", ""))
    ctx = build_market_context(
        row, symbol=symbol, timeframe=timeframe,
        range_engine=range_inner, trend_engine=trend_inner,
    )

    rule_dir = evaluate_variant_a(row, regime="TREND")
    ml_out = apply_trend_ml_filter(
        row,
        model=bundle.model,
        scaler=bundle.scaler,
        model_name="random_forest",
        threshold=float(bundle.config.get("threshold", 0.40)),
    )
    engine_action = ctx.trend_signal.signal
    trend_prob = float(ctx.trend_signal.probability)
    trend_pred = engine_action

    decision = stack.orchestrator.decide(ctx)
    compressed = float(decision.confidence)
    raw_conf = float(ctx.trend_signal.confidence)

    calibrated, risk = stack.risk.evaluate(ctx)
    cal_action = calibrated.final_action
    cal_conf = float(calibrated.final_confidence)

    mapped_trace = getattr(stack.risk, "last_mapping_trace", None) or {}
    mapped_conf = float(mapped_trace.get("mapped_confidence", cal_conf))
    mapped_ok = mapped_conf >= 0.55 or _actionable(cal_action)

    _cal2, risk2, quality = stack.quality.evaluate(ctx)
    risk_allowed = bool(risk.allowed)
    quality_allowed = bool(quality.allowed)

    kernel_action = cal_action if _actionable(cal_action) and risk_allowed and quality_allowed else "HOLD"
    final_signal = kernel_action

    stop = _detect_stop_stage(
        engine_action=engine_action,
        decision_action=decision.action,
        calibrated_action=cal_action,
        mapped_ok=mapped_ok or not _actionable(cal_action),
        risk_allowed=risk_allowed,
        quality_allowed=quality_allowed,
        kernel_action=kernel_action,
        final_signal=final_signal,
    )
    if stop not in VALID_STOP_STAGES:
        stop = "ENGINE"

    return TrendTraceRecord(
        timestamp=ts,
        symbol=symbol,
        regime=regime,
        selected_engine=engine_id,
        trend_probability=trend_prob,
        trend_prediction=trend_pred,
        raw_confidence=raw_conf,
        compressed_confidence=compressed,
        calibrated_confidence=cal_conf,
        mapped_confidence=mapped_conf,
        risk_allowed=risk_allowed,
        risk_reason=str(risk.blocked_by or risk.reason or ""),
        quality_allowed=quality_allowed,
        quality_reason=str(quality.blocked_by or quality.reason or ""),
        kernel_signal=kernel_action,
        final_signal=final_signal,
        stop_stage=stop,
    )


def trace_trend_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = 15,
    max_records: int = 2000,
) -> dict[str, Any]:
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase15a.engine_registry import EngineRegistry
    from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle

    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    PipelineCache.reset()
    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    range_inner, trend_inner = adapter._engine_inners()  # noqa: SLF001
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)

    records: list[TrendTraceRecord] = []
    stop_counts: dict[str, int] = {}

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        rec = trace_trend_bar(
            row, stack=stack, range_inner=range_inner, trend_inner=trend_inner,
            bundle=bundle, symbol=symbol, timeframe=timeframe,
        )
        if rec is None:
            continue
        records.append(rec)
        stop_counts[rec.stop_stage] = stop_counts.get(rec.stop_stage, 0) + 1
        if len(records) >= max_records:
            break

    return {
        "phase": "15J",
        "symbol": symbol,
        "timeframe": timeframe,
        "bars_traced": len(records),
        "stop_stage_counts": stop_counts,
        "primary_stop_stage": max(stop_counts, key=stop_counts.get) if stop_counts else "ENGINE",
        "records": [r.to_dict() for r in records],
    }
