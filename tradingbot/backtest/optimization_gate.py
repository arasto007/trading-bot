"""Explicit Phase 52 optimization gate.

Optimization is forbidden unless every mandatory condition passes.
This module never searches parameters.
"""

from __future__ import annotations

from typing import Any

BLOCKED = "BLOCKED"
PASSED = "PASSED"
CONDITION_IDS = (
    "commission_verified",
    "symbol_equivalence_verified",
    "executable_completed",
    "net_expectancy_positive",
    "event_net_expectancy_positive",
    "oos_net_positive",
    "oos_sample_sufficient",
    "bootstrap_not_obviously_fragile",
    "recent_not_materially_contradictory",
    "production_parity_not_fail",
    "no_material_unresolved_blocker",
    "robustness_not_fragile",
    "evidence_margin_exceeds_cost_uncertainty",
)


def evaluate_optimization_gate(
    *,
    commission_verified: bool,
    symbol_equivalence_verified: bool,
    executable_completed: bool,
    net_expectancy_R: float | None,
    event_net_expectancy_R: float | None,
    oos_net_expectancy_R: float | None,
    oos_sample_sufficient: bool,
    bootstrap_obviously_fragile: bool,
    recent_materially_contradictory: bool,
    production_parity_fail: bool,
    material_unresolved_blocker: bool,
    robustness_verdict: str,
    evidence_margin_exceeds_cost_uncertainty: bool,
) -> dict[str, Any]:
    rows = [
        ("commission_verified", bool(commission_verified), "Commission VERIFIED_SCHEDULE"),
        ("symbol_equivalence_verified", bool(symbol_equivalence_verified), "EV-EQ-01 VERIFIED"),
        (
            "executable_completed",
            bool(executable_completed),
            "Phase 48 executable completed with verified costs",
        ),
        (
            "net_expectancy_positive",
            bool(executable_completed and net_expectancy_R is not None and net_expectancy_R > 0),
            "Net expectancy after verified costs > 0",
        ),
        (
            "event_net_expectancy_positive",
            bool(
                executable_completed
                and event_net_expectancy_R is not None
                and event_net_expectancy_R > 0
            ),
            "Event-level net expectancy > 0",
        ),
        (
            "oos_net_positive",
            bool(executable_completed and oos_net_expectancy_R is not None and oos_net_expectancy_R > 0),
            "OOS net performance > 0",
        ),
        ("oos_sample_sufficient", bool(oos_sample_sufficient), "OOS sample sufficient"),
        (
            "bootstrap_not_obviously_fragile",
            not bool(bootstrap_obviously_fragile),
            "Bootstrap/distribution not obviously fragile",
        ),
        (
            "recent_not_materially_contradictory",
            not bool(recent_materially_contradictory),
            "Recent performance not materially contradictory",
        ),
        (
            "production_parity_not_fail",
            not bool(production_parity_fail),
            "Production/live parity no longer FAIL",
        ),
        (
            "no_material_unresolved_blocker",
            not bool(material_unresolved_blocker),
            "No unresolved blocker materially affecting profitability",
        ),
        (
            "robustness_not_fragile",
            str(robustness_verdict) != "FRAGILE",
            "Robustness verdict is not FRAGILE",
        ),
        (
            "evidence_margin_exceeds_cost_uncertainty",
            bool(evidence_margin_exceeds_cost_uncertainty),
            "Evidence margin larger than cost uncertainty",
        ),
    ]
    passed = [{"id": i, "ok": True, "label": label} for i, ok, label in rows if ok]
    failed = [{"id": i, "ok": False, "label": label} for i, ok, label in rows if not ok]
    status = PASSED if not failed else BLOCKED
    return {
        "OPTIMIZATION_GATE": status,
        "passed": passed,
        "failed": failed,
        "conditions_passed": len(passed),
        "conditions_failed": len(failed),
        "condition_count": len(CONDITION_IDS),
        "optimization_allowed": status == PASSED,
        "optimization_executed": False,
        "reason": "ALL_CONDITIONS_PASSED" if status == PASSED else failed[0]["id"],
    }


def unknown_commission_blocks_executable(commission_status: str, verified_schedule: bool) -> bool:
    return str(commission_status) != "VERIFIED" or verified_schedule is not True


def not_proven_symbol_blocks_ev_eq(ev_eq_01: str) -> bool:
    return str(ev_eq_01) != "VERIFIED"


def fragile_robustness_blocks_optimization(robustness_verdict: str) -> bool:
    return str(robustness_verdict) == "FRAGILE"
