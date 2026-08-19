"""Phase 14.8 — Phase 9.9 range engine audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.performance_analyzer import sharpe_like_stability


def audit_range_engine(
    full_records: list[dict[str, Any]],
    baseline_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    range_full = [r for r in full_records if r.get("allowed") and str(r.get("engine")) == "phase9_9"]
    metrics = trade_metrics_from_records(range_full)
    r_vals = [float(r["r_multiple"]) for r in range_full]

    baseline_range = []
    if baseline_records:
        baseline_range = [r for r in baseline_records if r.get("allowed")]

    return {
        "phase": "14.8",
        "engine": "phase9_9",
        "full_pipeline_trades": metrics["trades"],
        "baseline_trades": len(baseline_range),
        "profit_factor": metrics["profit_factor"],
        "expectancy": metrics["expectancy"],
        "win_rate": metrics["win_rate"],
        "max_drawdown": metrics["max_drawdown"],
        "sharpe_stability": sharpe_like_stability(r_vals),
        "contribution_pct": round(
            metrics["trades"] / max(sum(1 for r in full_records if r.get("allowed")), 1), 4
        ),
        "performance_stable": metrics["profit_factor"] >= 0 or metrics["trades"] == 0,
    }
