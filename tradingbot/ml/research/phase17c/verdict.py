"""Phase 17C — final verdict and recommendation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17c.config import (
    MAX_PF_DETERIORATION,
    MIN_CEILING_DELTA,
    MIN_THROUGHPUT_RATIO,
    VERDICTS,
)


def determine_verdict(
    *,
    shadow: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    range_reg: dict[str, Any],
    trend_quality: dict[str, Any],
    stability: dict[str, Any],
    safety: dict[str, Any],
) -> str:
    checks = build_checks(
        shadow=shadow,
        walk_forward=walk_forward,
        monte_carlo=monte_carlo,
        range_reg=range_reg,
        trend_quality=trend_quality,
        stability=stability,
        safety=safety,
    )

    if not checks["range_identical"] or not checks["no_production_changes"]:
        return "REJECT_CANDIDATE"

    if all(checks.values()):
        return "READY_FOR_PRODUCTION_BUNDLE"

    # Promising but incomplete
    if checks["trend_materially_improved"] and checks["range_identical"]:
        return "NEEDS_MORE_RESEARCH"

    return "REJECT_CANDIDATE"


def build_checks(
    *,
    shadow: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    range_reg: dict[str, Any],
    trend_quality: dict[str, Any],
    stability: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, bool]:
    summary = shadow.get("summary", {})
    win365 = summary.get("365d", {})

    trend_frozen = int(win365.get("trend_actionable_frozen", 0))
    trend_research = int(win365.get("trend_actionable_research", 0))
    pf_frozen = float(win365.get("pf_frozen", 0.0))
    pf_research = float(win365.get("pf_research", 0.0))
    ceiling_delta = float(trend_quality.get("deltas", {}).get("ceiling_delta", 0.0))

    throughput_ok = trend_research >= max(3, trend_frozen * MIN_THROUGHPUT_RATIO)
    pf_ok = (pf_research - pf_frozen) >= -MAX_PF_DETERIORATION

    return {
        "trend_materially_improved": throughput_ok and ceiling_delta >= MIN_CEILING_DELTA,
        "range_identical": bool(range_reg.get("passed")),
        "pf_not_degraded": pf_ok,
        "walk_forward_stable": bool(walk_forward.get("stability", {}).get("walk_forward_stable")),
        "monte_carlo_robust": bool(monte_carlo.get("robust")),
        "no_regression": bool(range_reg.get("passed")) and bool(safety.get("passed")),
        "no_production_changes": bool(safety.get("passed")),
        "bundle_reproducible": bool(stability.get("prediction_determinism", {}).get("passed"))
        and bool(stability.get("feature_consistency", {}).get("passed")),
        "stability_passed": bool(stability.get("passed")),
        "quality_improved": bool(trend_quality.get("materially_improved")),
    }


def build_recommendation(
    verdict: str,
    checks: dict[str, bool],
    shadow: dict[str, Any],
    trend_quality: dict[str, Any],
) -> dict[str, Any]:
    win365 = shadow.get("summary", {}).get("365d", {})
    return {
        "phase": "17C",
        "verdict": verdict,
        "checks": checks,
        "quantitative_summary": {
            "trend_actionable_frozen": win365.get("trend_actionable_frozen"),
            "trend_actionable_research": win365.get("trend_actionable_research"),
            "range_frozen": win365.get("range_frozen"),
            "range_research": win365.get("range_research"),
            "ceiling_delta": trend_quality.get("deltas", {}).get("ceiling_delta"),
            "spread_delta": trend_quality.get("deltas", {}).get("spread_delta"),
        },
        "production_bundle_replacement": False,
        "next_step": {
            "READY_FOR_PRODUCTION_BUNDLE": (
                "Phase 18A — Approved Production Bundle Freeze "
                "(explicit approval required; swap trend_rf only, keep phase9_9)"
            ),
            "NEEDS_MORE_RESEARCH": (
                "Phase 17D — Address failing gates (walk-forward / Monte Carlo / kernel TREND contribution)"
            ),
            "REJECT_CANDIDATE": (
                "Phase 17D — Revisit feature set or architecture per Phase 17A option 2"
            ),
        }.get(verdict, "Review reports"),
        "notes": [
            "Research RF+Top5 remains shadow-only.",
            "No production Trend bundle was replaced.",
            "RANGE engine must stay identical (phase9_9).",
        ],
    }


def build_final_report(
    *,
    verdict: str,
    checks: dict[str, bool],
    recommendation: dict[str, Any],
    shadow: dict[str, Any],
    walk_forward: dict[str, Any],
    monte_carlo: dict[str, Any],
    range_reg: dict[str, Any],
    trend_quality: dict[str, Any],
    stability: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "17C",
        "verdict": verdict,
        "read_only": True,
        "production_modified": False,
        "bundle_replaced": False,
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "recommendation": recommendation,
        "summary": {
            "shadow": shadow.get("summary"),
            "walk_forward_stable": walk_forward.get("stability", {}).get("walk_forward_stable"),
            "monte_carlo_robust": monte_carlo.get("robust"),
            "range_parity": range_reg.get("parity_pct"),
            "trend_quality_improved": trend_quality.get("materially_improved"),
            "stability_passed": stability.get("passed"),
            "safety_passed": safety.get("passed"),
        },
        "verdict_rationale": _rationale(verdict, checks, shadow, trend_quality),
    }


def _rationale(
    verdict: str,
    checks: dict[str, bool],
    shadow: dict[str, Any],
    trend_quality: dict[str, Any],
) -> str:
    win = shadow.get("summary", {}).get("365d", {})
    failed = [k for k, v in checks.items() if not v]
    if verdict == "READY_FOR_PRODUCTION_BUNDLE":
        return (
            f"All gates passed. TREND actionable {win.get('trend_actionable_research')} vs "
            f"{win.get('trend_actionable_frozen')}; RANGE identical; ceiling delta "
            f"{trend_quality.get('deltas', {}).get('ceiling_delta')}."
        )
    if verdict == "NEEDS_MORE_RESEARCH":
        return f"TREND improved and RANGE intact, but failing gates: {failed}."
    return f"Candidate rejected. Failed gates: {failed}."
