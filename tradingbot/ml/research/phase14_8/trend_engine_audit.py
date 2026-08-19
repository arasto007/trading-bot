"""Phase 14.8 — trend RF v40 engine audit."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_4.pipeline_simulator import trade_metrics_from_records
from tradingbot.ml.research.phase14_7.performance_analyzer import sharpe_like_stability


def audit_trend_engine(
    full_records: list[dict[str, Any]],
    *,
    walk_forward_windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trend = [r for r in full_records if r.get("allowed") and str(r.get("engine")) == "trend_rf_v40"]
    metrics = trade_metrics_from_records(trend)
    r_vals = [float(r["r_multiple"]) for r in trend]

    wf_pfs: list[float] = []
    if walk_forward_windows:
        for w in walk_forward_windows:
            if w.get("skipped"):
                continue
            eng = (w.get("engine_breakdown") or {}).get("trend_rf_v40", {})
            if eng:
                wf_pfs.append(float(eng.get("profit_factor", 0)))

    pf_stability = round(1.0 - (max(wf_pfs) - min(wf_pfs)) / max(max(wf_pfs), 0.01), 4) if len(wf_pfs) > 1 else 0.5

    return {
        "phase": "14.8",
        "engine": "trend_rf_v40",
        "trades": metrics["trades"],
        "profit_factor": metrics["profit_factor"],
        "expectancy": metrics["expectancy"],
        "win_rate": metrics["win_rate"],
        "max_drawdown": metrics["max_drawdown"],
        "sharpe_stability": sharpe_like_stability(r_vals),
        "contribution_pct": round(
            metrics["trades"] / max(sum(1 for r in full_records if r.get("allowed")), 1), 4
        ),
        "walk_forward_pf_stability": pf_stability,
        "walk_forward_windows": len(wf_pfs),
    }
