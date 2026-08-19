"""Phase 15I — RANGE pipeline path audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15i.signal_flow import trace_range_pipeline


def audit_range_pipeline(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    stride: int = 15,
) -> dict[str, Any]:
    flow = trace_range_pipeline(
        candles, dataset,
        base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        days=days, stride=stride,
    )
    drops = flow.get("drop_summary", {})
    primary = max(drops, key=drops.get) if drops else "none"
    return {
        "phase": "15I",
        "pipeline": "candles→regime→router→phase9_9→decision→calibration→mapping→risk→quality→kernel",
        **flow,
        "primary_drop_stage": primary,
        "primary_drop_count": drops.get(primary, 0),
        "diagnosis": _diagnose(drops, flow),
    }


def _diagnose(drops: dict[str, int], flow: dict[str, Any]) -> str:
    if flow.get("range_actionable_kernel", 0) > 0:
        return "range_path_partially_open"
    if drops.get("decision_14_1", 0) > 0:
        return "confidence_engine_compression_at_decision_14_1"
    if drops.get("phase9_9", 0) > 0:
        return "phase9_9_engine_hold_dominant"
    if drops.get("router", 0) > 0:
        return "router_not_selecting_phase9_9"
    if drops.get("risk_14_2b", 0) > 0:
        return "risk_gate_blocking_range"
    if drops.get("quality_14_3", 0) > 0:
        return "quality_gate_blocking_range"
    return "unknown_range_inactivity"
