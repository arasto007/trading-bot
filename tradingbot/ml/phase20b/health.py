"""Phase 20B — live system health score."""

from __future__ import annotations

from typing import Any


def _clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def compute_system_health(
    *,
    performance: dict[str, Any],
    drawdown: dict[str, Any],
    execution: dict[str, Any],
    filters: dict[str, Any],
    capital: dict[str, Any],
    trade_quality: dict[str, Any],
) -> dict[str, Any]:
    overall = performance.get("overall") or {}
    pf = float(overall.get("profit_factor", 0))
    exp = float(overall.get("expectancy_r", 0))
    trades = int(overall.get("trades", 0))
    dd = abs(float(drawdown.get("maximum_drawdown_r", 0)))

    # Execution stability
    lat_p95 = float((execution.get("latency") or {}).get("p95_ms", 0))
    rej = float(execution.get("rejection_rate", 0))
    if execution.get("broker_samples", 0) == 0:
        execution_score = 70.0  # no broker samples — neutral/limited
    else:
        execution_score = _clip(100 - max(0, lat_p95 - 50) * 0.5 - rej * 100)

    # Profitability stability
    profitability = _clip(30 * (pf - 0.5) + 40 * max(exp, 0) * 10 + min(trades, 50))

    # Risk control
    risk_control = _clip(100 - dd * 4 - int(drawdown.get("worst_loss_streak", 0)) * 3)

    # Filter effectiveness
    summary = filters.get("summary") or {}
    filt_map = {"effective": 100, "neutral": 70, "under_performing": 40, "over_restrictive": 30}
    rsi_s = filt_map.get(summary.get("rsi"), 50)
    adx_s = filt_map.get(summary.get("adx"), 50)
    both_s = filt_map.get(summary.get("combined"), 50)
    filter_score = (rsi_s + adx_s + both_s) / 3.0

    # Robustness (capital + quality)
    cap_ok = 90.0 if capital.get("passed") else 40.0
    quality = float(trade_quality.get("mean_overall_quality", 0)) * 100
    robustness = _clip(0.5 * cap_ok + 0.5 * quality)

    dimensions = {
        "execution_stability": round(execution_score, 1),
        "profitability_stability": round(profitability, 1),
        "risk_control_stability": round(risk_control, 1),
        "filter_effectiveness": round(filter_score, 1),
        "system_robustness": round(robustness, 1),
    }
    overall_score = round(sum(dimensions.values()) / len(dimensions), 1)

    return {
        "phase": "20B",
        "overall_score": overall_score,
        "dimensions": dimensions,
        "drivers": {
            "profit_factor": pf,
            "expectancy_r": exp,
            "trades": trades,
            "max_drawdown_r": dd,
            "latency_p95_ms": lat_p95,
            "rejection_rate": rej,
            "filter_summary": summary,
        },
    }
