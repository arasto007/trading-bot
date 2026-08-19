"""Phase 20C — final live production score."""

from __future__ import annotations

from typing import Any


def _clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def compute_final_live_score(
    *,
    data: dict[str, Any],
    audit: dict[str, Any],
    slippage: dict[str, Any],
    spread: dict[str, Any],
    latency: dict[str, Any],
    sim_vs_live: dict[str, Any],
    risk: dict[str, Any],
    stability: dict[str, Any],
    broker_quality: dict[str, Any],
) -> dict[str, Any]:
    if not data.get("has_sufficient_trades"):
        return {
            "phase": "20C",
            "status": "PENDING",
            "overall_score": None,
            "dimensions": {},
            "reason": "insufficient_real_trades",
            "real_fill_count": data.get("real_fill_count", 0),
            "min_required": data.get("min_required"),
        }

    # Execution quality
    fill_dist = (audit.get("summary") or {}).get("fill_quality_distribution") or {}
    good = fill_dist.get("EXCELLENT", 0) + fill_dist.get("GOOD", 0)
    total_q = sum(fill_dist.values()) or 1
    exec_quality = _clip(100 * good / total_q)

    # Broker quality
    fail_rate = broker_quality.get("failure_rate")
    if fail_rate is None:
        broker_score = 50.0
    else:
        broker_score = _clip(100 * (1.0 - float(fail_rate)))
    worst_slip = slippage.get("worst_slippage")
    if worst_slip is not None:
        broker_score = _clip(broker_score - min(30.0, float(worst_slip) * 10))

    # PnL consistency
    delta = sim_vs_live.get("delta")
    if delta is None:
        pnl_score = 50.0
    else:
        pf_gap = abs(float(delta.get("profit_factor", 0)))
        exp_gap = abs(float(delta.get("expectancy_r", 0)))
        pnl_score = _clip(100 - pf_gap * 40 - exp_gap * 50)

    # Operational stability
    stab_checks = stability.get("checks") or {}
    if stab_checks:
        stab_score = _clip(100 * sum(1 for v in stab_checks.values() if v) / len(stab_checks))
    else:
        stab_score = 50.0

    # Risk validation
    risk_score = 100.0 if risk.get("passed") else 40.0

    # Latency
    e2e = (latency.get("stages") or {}).get("end_to_end") or {}
    p95 = float(e2e.get("p95_ms", 0)) if e2e.get("status") == "COMPLETE" else 0.0
    latency_score = _clip(100 - max(0, p95 - 50) * 0.5) if p95 else 70.0

    dimensions = {
        "execution_quality": round(exec_quality, 1),
        "broker_quality": round(broker_score, 1),
        "pnl_consistency": round(pnl_score, 1),
        "operational_stability": round(stab_score, 1),
        "risk_validation": round(risk_score, 1),
        "latency": round(latency_score, 1),
    }
    overall = round(sum(dimensions.values()) / len(dimensions), 1)

    return {
        "phase": "20C",
        "status": "COMPLETE",
        "overall_score": overall,
        "dimensions": dimensions,
        "real_fill_count": data.get("real_fill_count"),
        "production_ready_threshold": 70.0,
        "meets_threshold": overall >= 70.0,
    }
