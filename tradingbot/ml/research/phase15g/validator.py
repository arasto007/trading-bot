"""Phase 15G — acceptance gate validation."""

from __future__ import annotations

from typing import Any


def validate_phase15g_results(
    *,
    bundle_audit: dict[str, Any],
    platt: dict[str, Any],
    ceiling: dict[str, Any],
    research_vs: dict[str, Any],
    equivalence: dict[str, Any],
    recovery: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "root_cause_identified": bool(recovery.get("why_frozen_never_reaches_riskgate")),
        "research_vs_frozen_quantified": research_vs.get("bars_compared", 0) > 0,
        "confidence_ceiling_measured": ceiling.get("maximum_calibrated_confidence") is not None,
        "equivalent_threshold_discovered": bool(
            equivalence.get("synthetic_equivalence")
            or equivalence.get("empirical_frozen_threshold_when_research_passes")
        ),
        "no_production_modifications": recovery.get("no_production_changes") is True,
        "bundle_probability_audited": bundle_audit.get("trend_bars_evaluated", 0) > 0,
        "platt_curve_generated": bool(platt.get("synthetic_curve")),
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "all_passed": passed,
        "failed": [k for k, v in checks.items() if not v],
    }
