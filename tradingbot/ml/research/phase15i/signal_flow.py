"""Phase 15I — per-bar RANGE signal flow tracing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame


@dataclass
class RangeFlowRecord:
    timestamp: str
    regime: str
    engine_selected: str | None
    range_signal: str
    range_probability: float
    range_confidence: float
    trend_signal: str
    decision_action: str
    decision_confidence: float
    calibrated_action: str
    calibrated_confidence: float
    mapped_confidence: float | None
    risk_allowed: bool
    risk_blocked_by: str | None
    quality_allowed: bool
    quality_blocked_by: str | None
    kernel_action: str
    drop_stage: str = ""
    drop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "regime": self.regime,
            "engine_selected": self.engine_selected,
            "range_signal": self.range_signal,
            "range_probability": round(self.range_probability, 6),
            "range_confidence": round(self.range_confidence, 6),
            "trend_signal": self.trend_signal,
            "decision_action": self.decision_action,
            "decision_confidence": round(self.decision_confidence, 6),
            "calibrated_action": self.calibrated_action,
            "calibrated_confidence": round(self.calibrated_confidence, 6),
            "mapped_confidence": (
                round(self.mapped_confidence, 6) if self.mapped_confidence is not None else None
            ),
            "risk_allowed": self.risk_allowed,
            "risk_blocked_by": self.risk_blocked_by,
            "quality_allowed": self.quality_allowed,
            "quality_blocked_by": self.quality_blocked_by,
            "kernel_action": self.kernel_action,
            "drop_stage": self.drop_stage,
            "drop_reason": self.drop_reason,
        }


def _assign_drop(record: RangeFlowRecord, stage: str, reason: str) -> None:
    if not record.drop_stage:
        record.drop_stage = stage
        record.drop_reason = reason


def trace_range_bar(
    row: pd.Series,
    *,
    stack: Any,
    range_inner: Any,
    trend_inner: Any,
    symbol: str,
    timeframe: str,
) -> RangeFlowRecord:
    ts = str(row.get("timestamp", ""))
    ctx = build_market_context(
        row, symbol=symbol, timeframe=timeframe,
        range_engine=range_inner, trend_engine=trend_inner,
    )
    engine_id = select_engine(ctx.regime)
    record = RangeFlowRecord(
        timestamp=ts,
        regime=ctx.regime,
        engine_selected=engine_id,
        range_signal=ctx.range_signal.signal,
        range_probability=float(ctx.range_signal.probability),
        range_confidence=float(ctx.range_signal.confidence),
        trend_signal=ctx.trend_signal.signal,
        decision_action="HOLD",
        decision_confidence=0.0,
        calibrated_action="HOLD",
        calibrated_confidence=0.0,
        mapped_confidence=None,
        risk_allowed=False,
        risk_blocked_by=None,
        quality_allowed=False,
        quality_blocked_by=None,
        kernel_action="HOLD",
    )

    decision = stack.orchestrator.decide(ctx)
    record.decision_action = decision.action
    record.decision_confidence = float(decision.confidence)

    if ctx.regime != "RANGE":
        record.drop_stage = "regime_not_range"
        record.drop_reason = f"regime={ctx.regime}"
        return record

    if engine_id != RANGE_MODEL_ID:
        _assign_drop(record, "router", f"engine={engine_id}")
        return record

    if record.range_signal not in ("BUY", "SELL"):
        _assign_drop(record, "phase9_9", "engine HOLD")
        return record

    if decision.action not in ("BUY", "SELL"):
        _assign_drop(record, "decision_14_1", "confidence policy gate")

    calibrated, risk = stack.risk.evaluate(ctx)
    record.calibrated_action = calibrated.final_action
    record.calibrated_confidence = float(calibrated.final_confidence)
    mapped_trace = getattr(stack.risk, "last_mapping_trace", None)
    if mapped_trace:
        record.mapped_confidence = float(mapped_trace.get("mapped_confidence", 0.0))
    record.risk_allowed = bool(risk.allowed)
    record.risk_blocked_by = risk.blocked_by

    if calibrated.final_action in ("BUY", "SELL") and not risk.allowed:
        _assign_drop(record, "risk_14_2b", str(risk.blocked_by or risk.reason))

    _cal2, _risk2, quality = stack.quality.evaluate(ctx)
    record.quality_allowed = bool(quality.allowed)
    record.quality_blocked_by = quality.blocked_by

    if calibrated.final_action in ("BUY", "SELL") and risk.allowed and not quality.allowed:
        _assign_drop(record, "quality_14_3", str(quality.blocked_by or quality.reason))

    action = str(calibrated.final_action)
    if action not in ("BUY", "SELL"):
        action = "HOLD"
    if not risk.allowed or not quality.allowed:
        action = "HOLD"
    record.kernel_action = action
    if calibrated.final_action in ("BUY", "SELL") and action == "HOLD" and not record.drop_stage:
        _assign_drop(record, "kernel", "coerced HOLD")

    return record


def trace_range_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    stride: int = 15,
    max_records: int = 500,
) -> dict[str, Any]:
    from datetime import timedelta

    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles

    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    if unified.empty:
        return {"records": [], "drop_summary": {}, "range_bars": 0}

    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    range_inner, trend_inner = adapter._engine_inners()  # noqa: SLF001

    records: list[RangeFlowRecord] = []
    drop_counts: dict[str, int] = {}
    range_bars = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
        if rule_classify_row(row) != "RANGE":
            continue
        range_bars += 1
        rec = trace_range_bar(
            row, stack=stack, range_inner=range_inner, trend_inner=trend_inner,
            symbol=symbol, timeframe=timeframe,
        )
        records.append(rec)
        if rec.drop_stage:
            drop_counts[rec.drop_stage] = drop_counts.get(rec.drop_stage, 0) + 1
        if len(records) >= max_records:
            break

    actionable = sum(1 for r in records if r.kernel_action in ("BUY", "SELL"))
    return {
        "phase": "15I",
        "range_bars_traced": range_bars,
        "records_sampled": len(records),
        "range_actionable_kernel": actionable,
        "drop_summary": drop_counts,
        "sample_records": [r.to_dict() for r in records[:50]],
    }
