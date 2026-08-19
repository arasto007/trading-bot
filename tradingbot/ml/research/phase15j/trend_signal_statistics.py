"""Phase 15J — trend signal statistics."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15j.config import ENGINE_COLLAPSE_THRESHOLD, TREND_ENGINE_ID
from tradingbot.ml.research.phase15j.trend_pipeline_trace import trace_trend_pipeline


def compute_trend_statistics(
    trace_report: dict[str, Any],
) -> dict[str, Any]:
    records = trace_report.get("records", [])
    if not records:
        return {"phase": "15J", "trend_bars": 0, "engine_collapse": True}

    trend_bars = len(records)
    router_trend = trend_bars
    buy = sum(1 for r in records if r.get("trend_prediction") == "BUY")
    sell = sum(1 for r in records if r.get("trend_prediction") == "SELL")
    hold = trend_bars - buy - sell

    def _pass_pct(stage: str) -> float:
        stopped = sum(1 for r in records if r.get("stop_stage") == stage)
        passed = trend_bars - stopped
        for s in ("ENGINE", "DECISION", "CALIBRATION", "MAPPING", "RISK", "QUALITY", "KERNEL"):
            if s == stage:
                break
            passed = sum(1 for r in records if _stage_index(r.get("stop_stage", "")) > _stage_index(s))
        return round(passed / max(trend_bars, 1), 4)

    engine_out = buy + sell
    engine_pct = engine_out / max(trend_bars, 1)
    flags: list[str] = []
    if engine_pct < ENGINE_COLLAPSE_THRESHOLD:
        flags.append("ENGINE_COLLAPSE")

    stop_counts = trace_report.get("stop_stage_counts", {})
    return {
        "phase": "15J",
        "trend_bars": trend_bars,
        "router_trend_selections": router_trend,
        "trend_buy": buy,
        "trend_sell": sell,
        "trend_hold": hold,
        "engine_output_pct": round(engine_pct, 4),
        "decision_pass_pct": _stage_pass_rate(records, "DECISION"),
        "calibration_pass_pct": _stage_pass_rate(records, "CALIBRATION"),
        "mapping_pass_pct": _stage_pass_rate(records, "MAPPING"),
        "risk_pass_pct": _stage_pass_rate(records, "RISK"),
        "quality_pass_pct": _stage_pass_rate(records, "QUALITY"),
        "kernel_pass_pct": _stage_pass_rate(records, "KERNEL"),
        "stop_stage_counts": stop_counts,
        "primary_stop_stage": trace_report.get("primary_stop_stage"),
        "flags": flags,
        "selected_engine": TREND_ENGINE_ID,
    }


_STAGE_ORDER = ["ENGINE", "DECISION", "CALIBRATION", "MAPPING", "RISK", "QUALITY", "KERNEL", "NONE"]


def _stage_index(stage: str) -> int:
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return 0


def _stage_pass_rate(records: list[dict[str, Any]], stage: str) -> float:
    idx = _stage_index(stage)
    passed = sum(1 for r in records if _stage_index(r.get("stop_stage", "ENGINE")) > idx)
    return round(passed / max(len(records), 1), 4)


def run_trend_statistics(
    candles,
    dataset,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = 15,
) -> dict[str, Any]:
    trace = trace_trend_pipeline(
        candles, dataset, base_dir=base_dir, symbol=symbol, timeframe=timeframe,
        days=days, stride=stride,
    )
    stats = compute_trend_statistics(trace)
    stats["trace_bars"] = trace.get("bars_traced", 0)
    return stats
