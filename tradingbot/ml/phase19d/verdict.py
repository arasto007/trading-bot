"""Phase 19D — final certification verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19d.config import VERDICTS


def build_certification_gates(deployment: dict[str, Any]) -> dict[str, bool]:
    return dict(deployment.get("gates", {}))


def determine_verdict(
    *,
    deployment: dict[str, Any],
    final_score: dict[str, Any],
    certification: dict[str, Any],
) -> str:
    gates = deployment.get("gates", {})
    all_pass = deployment.get("all_gates_pass", False)
    overall = float(final_score.get("overall_score", 0))

    perf_3y = certification.get("windows", {}).get("1095d", {}).get("performance", {})
    pf = float(perf_3y.get("profit_factor", 0))
    exp = float(perf_3y.get("expectancy_r", 0))
    dd = abs(float(perf_3y.get("maximum_drawdown_r", 0)))

    full_criteria = (
        all_pass
        and overall >= 70
        and pf >= 1.30
        and exp >= 0.15
        and dd <= 20.0
        and gates.get("live_safety_passed", False)
        and gates.get("montecarlo_passed", False)
        and gates.get("walkforward_stable", False)
    )
    if full_criteria:
        return "APPROVED_FOR_FULL_PRODUCTION"

    small_criteria = (
        gates.get("backtest_certification", False)
        and gates.get("live_safety_passed", False)
        and gates.get("capital_simulation_passed", False)
        and pf >= 1.10
        and exp >= 0
        and overall >= 55
    )
    if small_criteria:
        return "APPROVED_FOR_SMALL_CAPITAL"

    return "NOT_APPROVED_FOR_LIVE"


def build_final_report(
    *,
    verdict: str,
    certification: dict[str, Any],
    deployment: dict[str, Any],
    final_score: dict[str, Any],
    audit: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stress: dict[str, Any],
    capital: dict[str, Any],
    live_safety: dict[str, Any],
) -> dict[str, Any]:
    perf_3y = certification.get("windows", {}).get("1095d", {}).get("performance", {})
    return {
        "phase": "19D",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "read_only": True,
        "production_modified": False,
        "system_under_test": certification.get("system_under_test"),
        "performance_3y": perf_3y,
        "final_score": final_score,
        "deployment_gates": deployment.get("gates"),
        "all_gates_pass": deployment.get("all_gates_pass"),
        "audit": {
            "passed": audit.get("passed"),
            "dimensions": audit.get("dimensions"),
        },
        "walkforward": {
            "stable": walkforward.get("stable"),
            "passed": walkforward.get("passed"),
        },
        "montecarlo": {
            "passed": montecarlo.get("passed"),
            "max_failure_rate": montecarlo.get("max_failure_rate"),
        },
        "stress_test": {
            "passed": stress.get("passed"),
            "segments_passed": stress.get("segments_passed"),
        },
        "capital": {
            "passed": capital.get("passed"),
            "levels": capital.get("levels"),
        },
        "live_safety": {
            "passed": live_safety.get("passed"),
            "checks": live_safety.get("checks"),
        },
        "recommendation": {
            "APPROVED_FOR_FULL_PRODUCTION": (
                "All certification gates passed — approved for full production capital deployment."
            ),
            "APPROVED_FOR_SMALL_CAPITAL": (
                "Certification passed with caveats — deploy with limited capital and monitoring."
            ),
            "NOT_APPROVED_FOR_LIVE": (
                "Certification gates failed — do not deploy real capital until issues are resolved."
            ),
        }.get(verdict, ""),
    }
