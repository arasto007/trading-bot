"""Phase 17B — final verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17b.config import VERDICTS


def determine_verdict(acceptance: dict[str, Any], comparison: dict[str, Any]) -> str:
    if acceptance.get("hard_failures"):
        return "REJECT_NEW_RF"

    checks = acceptance.get("checks", {})
    deltas = comparison.get("deltas", {})

    core_pass = (
        checks.get("ceiling_improves")
        and checks.get("throughput_improves")
        and checks.get("range_identical")
        and checks.get("pf_not_deteriorated")
        and checks.get("latency_acceptable")
    )

    if acceptance.get("all_passed") and core_pass:
        return "READY_FOR_SHADOW_BUNDLE"

    promising = (
        deltas.get("ceiling_delta", 0) > 0
        and checks.get("range_identical")
        and not checks.get("hard_failures")
        and (
            checks.get("throughput_improves")
            or deltas.get("roc_auc_delta", 0) > 0
        )
    )
    if promising:
        return "PROMISING_NEEDS_WORK"

    return "REJECT_NEW_RF"


def build_final_report(
    *,
    verdict: str,
    acceptance: dict[str, Any],
    comparison: dict[str, Any],
    shadow: dict[str, Any],
    training: dict[str, Any],
    research_meta: dict[str, Any],
) -> dict[str, Any]:
    q = acceptance.get("quantitative", {})
    return {
        "phase": "17B",
        "verdict": verdict,
        "read_only": True,
        "production_modified": False,
        "bundle_frozen": False,
        "summary": {
            "frozen_ceiling": comparison.get("frozen", {}).get("ceiling"),
            "research_ceiling": comparison.get("research", {}).get("ceiling"),
            "ceiling_delta": comparison.get("deltas", {}).get("ceiling_delta"),
            "trend_actionable_frozen": q.get("trend_actionable_frozen"),
            "trend_actionable_research": q.get("trend_actionable_research"),
            "range_kernel_unchanged": acceptance.get("checks", {}).get("range_identical"),
            "walk_forward_mean_auc": training.get("walk_forward_mean_auc"),
            "acceptance_passed": acceptance.get("all_passed"),
        },
        "verdict_rationale": _rationale(verdict, acceptance, comparison),
        "research_model": research_meta,
        "next_step": _next_step(verdict),
    }


def _rationale(verdict: str, acceptance: dict[str, Any], comparison: dict[str, Any]) -> str:
    d = comparison.get("deltas", {})
    q = acceptance.get("quantitative", {})
    if verdict == "READY_FOR_SHADOW_BUNDLE":
        return (
            f"Research RF ceiling {comparison.get('research', {}).get('ceiling')} vs frozen "
            f"{comparison.get('frozen', {}).get('ceiling')} (delta {d.get('ceiling_delta')}); "
            f"TREND actionable {q.get('trend_actionable_research')} vs {q.get('trend_actionable_frozen')}; "
            f"RANGE kernel identical; all acceptance checks passed."
        )
    if verdict == "PROMISING_NEEDS_WORK":
        return (
            f"Material improvement detected (ceiling delta {d.get('ceiling_delta')}, "
            f"actionable {q.get('trend_actionable_research')} vs {q.get('trend_actionable_frozen')}) "
            "but not all acceptance gates passed — needs walk-forward stability or PF tuning."
        )
    return (
        f"Candidate failed acceptance: hard_failures={acceptance.get('hard_failures')}; "
        f"checks_passed={acceptance.get('passed_count')}/{acceptance.get('total_checks')}."
    )


def _next_step(verdict: str) -> str:
    mapping = {
        "READY_FOR_SHADOW_BUNDLE": "Phase 17C — Extended Shadow Bundle Validation (30d live shadow, still no production swap)",
        "PROMISING_NEEDS_WORK": "Phase 17C — Refine feature stability + conservative hyperparameter sweep (research only)",
        "REJECT_NEW_RF": "Phase 17C — Revisit feature set or alternative model per Phase 17A option 2",
    }
    return mapping.get(verdict, mapping["REJECT_NEW_RF"])
