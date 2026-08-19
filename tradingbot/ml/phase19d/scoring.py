"""Phase 19D — final composite score."""

from __future__ import annotations

from typing import Any


def compute_final_score(
    *,
    certification: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stress: dict[str, Any],
    capital: dict[str, Any],
    live_safety: dict[str, Any],
) -> dict[str, Any]:
    def _clip(x: float) -> float:
        return max(0.0, min(100.0, x))

    perf_3y = certification.get("windows", {}).get("1095d", {}).get("performance", {})
    pf = float(perf_3y.get("profit_factor", 0))
    exp = float(perf_3y.get("expectancy_r", 0))
    wr = float(perf_3y.get("win_rate", 0))
    dd = abs(float(perf_3y.get("maximum_drawdown_r", 0)))

    profitability = _clip(30 * (pf - 0.5) + 20 * max(exp, 0) * 10 + 20 * wr)
    robustness = _clip(100 * (1.0 - float(montecarlo.get("max_failure_rate", 1.0))))
    consistency = _clip(100 * min(1.0, pf / 1.5) * (1.0 if walkforward.get("stable") else 0.5))
    risk_score = _clip(100 - dd * 5)

    cap_1000 = capital.get("levels", {}).get("1000", {})
    ruin = cap_1000.get("risk_of_ruin", True)
    capital_score = _clip(0 if ruin else 70 + float(cap_1000.get("total_return_pct", 0)))

    architecture = 95.0 if live_safety.get("passed") else 70.0
    deployment = 95.0 if all(
        (
            certification.get("passed"),
            walkforward.get("passed"),
            montecarlo.get("passed"),
            live_safety.get("passed"),
        )
    ) else 55.0

    dimensions = {
        "architecture": round(architecture, 1),
        "profitability": round(profitability, 1),
        "robustness": round(robustness, 1),
        "consistency": round(consistency, 1),
        "risk": round(risk_score, 1),
        "deployment": round(deployment, 1),
        "capital": round(capital_score, 1),
    }
    overall = round(sum(dimensions.values()) / len(dimensions), 1)

    return {
        "phase": "19D",
        "overall_score": overall,
        "dimensions": dimensions,
        "drivers": {
            "profit_factor_3y": pf,
            "expectancy_3y": exp,
            "win_rate_3y": wr,
            "max_drawdown_3y_r": dd,
            "walkforward_stable": walkforward.get("stable"),
            "montecarlo_failure_rate": montecarlo.get("max_failure_rate"),
            "stress_segments_passed": stress.get("segments_passed"),
            "risk_of_ruin_1000": ruin,
            "live_safety_passed": live_safety.get("passed"),
        },
    }
