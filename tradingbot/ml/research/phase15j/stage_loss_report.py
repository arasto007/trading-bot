"""Phase 15J — stage loss funnel report."""

from __future__ import annotations

from typing import Any


_STAGE_FUNNEL = [
    "Router",
    "Engine",
    "Decision",
    "Calibration",
    "Mapping",
    "Risk",
    "Quality",
    "Kernel",
    "Signal",
]

_MAP = {
    "Router": None,
    "Engine": "ENGINE",
    "Decision": "DECISION",
    "Calibration": "CALIBRATION",
    "Mapping": "MAPPING",
    "Risk": "RISK",
    "Quality": "QUALITY",
    "Kernel": "KERNEL",
    "Signal": "NONE",
}


def build_stage_loss_report(
    trace_report: dict[str, Any],
    statistics: dict[str, Any],
) -> dict[str, Any]:
    records = trace_report.get("records", [])
    trend_bars = len(records)
    stop_counts = trace_report.get("stop_stage_counts", {})

    stages: list[dict[str, Any]] = []
    prev_out = trend_bars

    for stage in _STAGE_FUNNEL:
        if stage == "Router":
            inp = trend_bars
            out = trend_bars
        elif stage == "Signal":
            inp = prev_out
            out = sum(1 for r in records if r.get("stop_stage") == "NONE")
        else:
            key = _MAP[stage]
            stopped = stop_counts.get(key, 0) if key else 0
            inp = prev_out
            out = max(0, inp - stopped)
        loss = inp - out
        stages.append({
            "stage": stage,
            "input": inp,
            "output": out,
            "loss": loss,
            "loss_pct": round(loss / max(inp, 1), 4),
        })
        prev_out = out

    return {
        "phase": "15J",
        "funnel": stages,
        "primary_stop_stage": statistics.get("primary_stop_stage"),
        "total_trend_bars": trend_bars,
        "final_signals": stages[-1]["output"] if stages else 0,
    }
