"""Phase 16C — TREND pipeline funnel tracing (read-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import TREND_ML_THRESHOLD
from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase16c.config import DECISION_MIN_CONFIDENCE, RF_THRESHOLD
from tradingbot.ml.research.phase16c.rule_diagnostics import diagnose_rule_gates
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _actionable(action: str) -> bool:
    return str(action).upper() in ("BUY", "SELL")


def trace_trend_funnel_bar(
    row: pd.Series,
    *,
    stack: Any,
    range_inner: Any,
    trend_inner: Any,
    bundle: Any,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Trace one TREND bar through every pipeline stage."""
    regime = rule_classify_row(row)
    if regime != "TREND":
        return {}

    rule_diag = diagnose_rule_gates(row, regime="TREND")
    rule_dir = rule_diag["direction"]

    aligned_row = (
        trend_inner.aligner.align_row(row)
        if getattr(trend_inner, "aligner", None) is not None
        else row
    )
    ml = apply_trend_ml_filter(
        aligned_row,
        model=bundle.model,
        scaler=bundle.scaler,
        model_name="random_forest",
        threshold=RF_THRESHOLD,
    )
    prob = float(ml["probability"])
    rf_pass = prob >= RF_THRESHOLD and rule_dir in ("BUY", "SELL")

    ctx = build_market_context(
        row, symbol=symbol, timeframe=timeframe,
        range_engine=range_inner, trend_engine=trend_inner,
    )
    engine_action = ctx.trend_signal.signal

    decision = stack.orchestrator.decide(ctx)
    decision_pass = _actionable(decision.action)

    calibrated, risk = stack.risk.evaluate(ctx)
    cal_pass = _actionable(calibrated.final_action)

    mapped_trace = getattr(stack.risk, "last_mapping_trace", None) or {}
    mapped_conf = float(mapped_trace.get("mapped_confidence", calibrated.final_confidence))
    mapping_pass = mapped_conf >= DECISION_MIN_CONFIDENCE or not _actionable(calibrated.final_action)

    _cal2, risk2, quality = stack.quality.evaluate(ctx)
    risk_pass = bool(risk.allowed)
    quality_pass = bool(quality.allowed)

    kernel_action = (
        calibrated.final_action
        if _actionable(calibrated.final_action) and risk_pass and quality_pass
        else "HOLD"
    )
    kernel_pass = _actionable(kernel_action)

    return {
        "timestamp": str(row.get("timestamp", "")),
        "regime": regime,
        "rule_direction": rule_dir,
        "rule_diag": rule_diag,
        "probability": prob,
        "probability_raw": float(ml["probability"]),
        "rf_pass": rf_pass,
        "engine_action": engine_action,
        "decision_action": decision.action,
        "decision_confidence": float(decision.confidence),
        "calibrated_action": calibrated.final_action,
        "calibrated_confidence": float(calibrated.final_confidence),
        "mapped_confidence": mapped_conf,
        "risk_allowed": risk_pass,
        "quality_allowed": quality_pass,
        "kernel_action": kernel_action,
        "stages": {
            "trend_bars": 1,
            "rule_pass": 1 if rule_dir in ("BUY", "SELL") else 0,
            "rf_pass": 1 if rf_pass else 0,
            "decision_pass": 1 if decision_pass else 0,
            "calibration_pass": 1 if cal_pass else 0,
            "mapping_pass": 1 if mapping_pass and cal_pass else 0,
            "risk_pass": 1 if risk_pass and cal_pass else 0,
            "quality_pass": 1 if quality_pass and cal_pass and risk_pass else 0,
            "kernel_output": 1 if kernel_pass else 0,
        },
        "features": {k: float(row.get(k, 0.0)) for k in bundle.feature_order},
        "adx": float(row.get("adx", 0)),
        "atr_percentile": float(row.get("atr_percentile", 0)),
        "session": str(row.get("session", "unknown")),
    }


def build_trend_funnel(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = 5,
) -> dict[str, Any]:
    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    range_inner, trend_inner = adapter._engine_inners()  # noqa: SLF001
    bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)

    records: list[dict[str, Any]] = []
    funnel_counts = {
        "trend_bars": 0,
        "rule_pass": 0,
        "rf_pass": 0,
        "decision_pass": 0,
        "calibration_pass": 0,
        "mapping_pass": 0,
        "risk_pass": 0,
        "quality_pass": 0,
        "kernel_output": 0,
    }

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        if rule_classify_row(row) != "TREND":
            continue
        rec = trace_trend_funnel_bar(
            row, stack=stack, range_inner=range_inner, trend_inner=trend_inner,
            bundle=bundle, symbol=symbol, timeframe=timeframe,
        )
        if not rec:
            continue
        records.append(rec)
        funnel_counts["trend_bars"] += 1
        for k in funnel_counts:
            if k != "trend_bars":
                funnel_counts[k] += rec["stages"].get(k, 0)

    n = funnel_counts["trend_bars"] or 1
    drop_rates = {}
    prev = n
    for stage in ("rule_pass", "rf_pass", "decision_pass", "calibration_pass",
                  "mapping_pass", "risk_pass", "quality_pass", "kernel_output"):
        cur = funnel_counts[stage]
        drop_rates[stage] = {
            "count": cur,
            "survival_rate": round(cur / n, 6),
            "drop_from_prior": round((prev - cur) / max(prev, 1), 6),
        }
        prev = cur

    return {
        "phase": "16C",
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "stride": stride,
        "funnel_counts": funnel_counts,
        "funnel_rates": {k: round(funnel_counts[k] / n, 6) for k in funnel_counts},
        "stage_survival": drop_rates,
        "records": records,
        "rf_threshold": RF_THRESHOLD,
        "decision_min_confidence": DECISION_MIN_CONFIDENCE,
        "trend_ml_threshold_production": TREND_ML_THRESHOLD,
    }
