"""Phase 14.7 — pipeline performance metrics."""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.trade_tracker import accepted_trades


def sharpe_like_stability(r_values: list[float]) -> float:
    if len(r_values) < 2:
        return 0.0
    std = statistics.pstdev(r_values)
    if std <= 1e-9:
        return 2.0 if sum(r_values) > 0 else 0.0
    return round(float(np.mean(r_values) / std), 4)


def analyze_performance(records: list[dict[str, Any]], *, stride: int = 1) -> dict[str, Any]:
    base = trade_metrics_from_records(records)
    accepted = accepted_trades(records)
    r_vals = [float(r["r_multiple"]) for r in accepted]
    conf_vals = [float(r["confidence"]) for r in accepted if r.get("confidence") is not None]
    risk_vals = [float(r["risk_percent"]) for r in accepted if r.get("risk_percent")]
    quality_vals = [float(r["quality_score"]) for r in accepted if r.get("quality_score")]

    return {
        **base,
        "effective_trades_est": int(base["trades"] * max(1, stride)),
        "accepted_trades": len(accepted),
        "sharpe_like_stability": sharpe_like_stability(r_vals),
        "avg_confidence": round(statistics.mean(conf_vals), 4) if conf_vals else 0.0,
        "avg_risk_percent": round(statistics.mean(risk_vals), 4) if risk_vals else 0.0,
        "avg_quality_score": round(statistics.mean(quality_vals), 4) if quality_vals else 0.0,
        "block_reasons": _block_reasons(records),
    }


def _block_reasons(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        if not r.get("allowed") and r.get("raw_signal") in ("BUY", "SELL"):
            reason = str(r.get("block_reason") or "unknown")
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def compare_pipelines(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = results.get("phase9_9_baseline", {})
    router = results.get("phase13_10_router", {})
    full = results.get("phase14_full", {})
    return {
        "phase": "14.7",
        "baseline_pf": baseline.get("profit_factor", 0),
        "router_pf": router.get("profit_factor", 0),
        "full_pf": full.get("profit_factor", 0),
        "full_beats_baseline": float(full.get("profit_factor", 0)) >= float(baseline.get("profit_factor", 0)),
        "pf_improvement_vs_baseline": round(
            float(full.get("profit_factor", 0)) - float(baseline.get("profit_factor", 0)), 4
        ),
        "expectancy_improvement": round(
            float(full.get("expectancy", 0)) - float(baseline.get("expectancy", 0)), 4
        ),
        "trade_delta_full_vs_baseline": int(full.get("effective_trades_est", 0))
        - int(baseline.get("effective_trades_est", 0)),
    }
