"""Phase 19B — research verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase19b.config import VERDICTS


def determine_verdict(recommendations: dict[str, Any]) -> str:
    safe = recommendations.get("safe_improvements") or []
    # Require at least one filter that improves PF and expectancy without blowing DD
    for item in safe:
        impact = item.get("expected_impact", {})
        if impact.get("profit_factor", 0) > 0 and impact.get("expectancy", 0) >= 0:
            if impact.get("max_drawdown", 0) <= 5:  # DD not much worse
                return "SAFE_IMPROVEMENTS_AVAILABLE"
    return "NO_SAFE_IMPROVEMENT_FOUND"


def build_final_report(
    *,
    verdict: str,
    recommendations: dict[str, Any],
    loss: dict[str, Any],
    winners: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "19B",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "read_only": True,
        "production_modified": False,
        "no_bundle_replacement": True,
        "no_kernel_changes": True,
        "baseline": recommendations.get("baseline"),
        "targets": recommendations.get("targets"),
        "top_improvements": recommendations.get("top_improvements", []),
        "safe_count": len(recommendations.get("safe_improvements") or []),
        "walkforward_survivors": len(walkforward.get("survivors") or []),
        "montecarlo_passed": len(montecarlo.get("passed") or []),
        "loss_patterns": (loss.get("recurring_patterns") or [])[:5],
        "top_win_predictors": (winners.get("top_predictors") or [])[:5],
        "recommendation": (
            "Safe filter candidates available for a future approved research→production phase. "
            "Do not implement until explicit approval."
            if verdict == "SAFE_IMPROVEMENTS_AVAILABLE"
            else "No walk-forward + Monte-Carlo validated improvement found. Keep current production config."
        ),
    }
