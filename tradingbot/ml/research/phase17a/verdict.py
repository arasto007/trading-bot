"""Phase 17A — final verdict from prior-phase evidence."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.config import EVIDENCE, VERDICTS


def determine_verdict(
    scores: dict[str, Any],
    compatibility: dict[str, Any],
    risks: dict[str, Any],
    roadmap: dict[str, Any],
) -> str:
    """
    Smallest production-safe upgrade that restores TREND without harming RANGE.

    Evidence chain:
    - 16A/16B: alignment restores ceiling to ~0.44 but throughput remains ~1 signal.
    - 16C: rules pass 86%; RF is the bottleneck; threshold lowering does not help.
    - 16D: FEATURE_SET primary (1.0) + RF architecture secondary (0.7); labels OK.
      Surrogate RF on existing features alone reaches max P ~0.69 → RF class is capable
      when retrained; frozen bundle is saturated.
      Surrogate RF + top features reaches ~0.84 → features are the primary unlock.
    """
    by_id = {c["id"]: c for c in scores["candidates"]}
    option1 = roadmap["options"][0]["architecture_id"]

    # Status quo fails hard checks from 16B/16C.
    if EVIDENCE["phase16c_rf_pass"] <= 1 and EVIDENCE["phase16c_kernel_trend"] == 0:
        keep_rf_viable = False
    else:
        keep_rf_viable = True

    if keep_rf_viable:
        return "KEEP_RF"

    # Primary limitation is missing information; RF class still works when retrained.
    feature_primary = EVIDENCE["phase16d_feature_score"] >= 0.8
    arch_secondary = EVIDENCE["phase16d_arch_score"] < EVIDENCE["phase16d_feature_score"]
    labels_ok = EVIDENCE["phase16d_label_score"] < 0.3
    rf_plus = by_id.get("C", {})
    rf_plus_balance = rf_plus.get("composite_balance", 0.0)

    # Smallest production-safe path: RF + top features (option C).
    # Primary limitation is missing information; RF class remains capable when
    # retrained (16D surrogate existing-only max P≈0.69). Boosting/stacking
    # are performance options, not the minimal upgrade.
    compat_c = next(
        (r for r in compatibility["rows"] if r["id"] == "C"),
        {"overall": "major_work"},
    )
    risk_c = next((r for r in risks["rows"] if r["id"] == "C"), {"mean_risk": 1.0})

    if (
        feature_primary
        and labels_ok
        and compat_c["overall"] in ("fully_compatible", "minor_work")
        and risk_c["mean_risk"] < 0.5
        and rf_plus_balance > 0.4
    ):
        return "RF_PLUS_FEATURES"

    # Escalation only if RF+features is incompatible or high-risk.
    if option1 in ("F", "G"):
        return "LIGHTGBM_RECOMMENDED"
    if option1 in ("H", "I"):
        return "XGBOOST_RECOMMENDED"
    if option1 in ("J", "K", "L"):
        return "STACKED_MODEL_RECOMMENDED"
    if option1 in ("C", "B"):
        return "RF_PLUS_FEATURES"
    if option1 in ("D", "E"):
        return "OTHER"

    return "RF_PLUS_FEATURES"


def evidence_narrative(verdict: str) -> list[str]:
    return [
        (
            f"Phase 16A: Feature alignment raised max P from "
            f"{EVIDENCE['phase16a_max_p_before']} to {EVIDENCE['phase16a_max_p_after']} "
            "without changing the frozen bundle."
        ),
        (
            f"Phase 16B: TREND engine actionable={EVIDENCE['phase16b_trend_actionable_365d']} "
            f"while RANGE kernel trades={EVIDENCE['phase16b_range_kernel_365d']} — "
            "RANGE path is healthy and must stay isolated."
        ),
        (
            f"Phase 16C: Rule pass rate={EVIDENCE['phase16c_rule_pass_rate']}; "
            f"RF pass={EVIDENCE['phase16c_rf_pass']}; kernel TREND={EVIDENCE['phase16c_kernel_trend']}. "
            "Rules and thresholds are not the bottleneck."
        ),
        (
            f"Phase 16D: primary={EVIDENCE['phase16d_primary']} "
            f"(feature={EVIDENCE['phase16d_feature_score']}, "
            f"arch={EVIDENCE['phase16d_arch_score']}, "
            f"label={EVIDENCE['phase16d_label_score']}). "
            f"Surrogate existing-only max P={EVIDENCE['phase16d_surrogate_existing_max_p']}; "
            f"with top features max P={EVIDENCE['phase16d_surrogate_combined_max_p']}."
        ),
        (
            f"Verdict {verdict}: smallest production-safe path is retrain RF on current + top-5 "
            "features (option C). Preserves sklearn interface, RiskGate/DecisionPolicy, "
            "and phase9_9 RANGE isolation; avoids LightGBM/XGBoost/stacking ops surface "
            "until RF+features is proven insufficient in shadow."
        ),
    ]


def build_final_report(
    *,
    verdict: str,
    scores: dict[str, Any],
    compatibility: dict[str, Any],
    maintenance: dict[str, Any],
    risks: dict[str, Any],
    roadmap: dict[str, Any],
) -> dict[str, Any]:
    option1 = roadmap["options"][0]
    return {
        "phase": "17A",
        "verdict": verdict,
        "read_only": True,
        "production_modified": False,
        "question": (
            "What is the SMALLEST production-safe upgrade path that restores a healthy "
            "TREND engine without sacrificing the validated RANGE engine?"
        ),
        "answer": {
            "architecture_id": "C",
            "name": "New RF + Top 5 features",
            "verdict_code": verdict,
        },
        "roadmap_option_1": option1,
        "evidence": evidence_narrative(verdict),
        "evidence_anchors": dict(EVIDENCE),
        "why_not_keep_rf": "Frozen RF max P≈0.44 with ~1 TREND signal; status quo fails throughput.",
        "why_not_lightgbm_first": (
            "Higher expected performance but minor/major kernel dependency work; "
            "RF+features addresses primary information gap with lower risk."
        ),
        "why_not_stacked_first": "Highest deployment/rollback complexity; not smallest path.",
        "range_engine_guarantee": "phase9_9 remains frozen and isolated",
        "next_phase_recommendation": (
            "Phase 17B — Offline RF+Top5 Chronological Retrain Lab "
            "(research-only bundle, shadow replay, no production swap)"
        ),
        "no_models_implemented": True,
    }


def build_executive_markdown(final: dict[str, Any], roadmap: dict[str, Any]) -> str:
    lines = [
        "# Phase 17A — Executive Recommendation",
        "",
        f"**Verdict:** `{final['verdict']}`",
        "",
        f"**Question:** {final['question']}",
        "",
        f"**Answer:** {final['answer']['name']} (architecture {final['answer']['architecture_id']})",
        "",
        "## Evidence",
        "",
    ]
    for e in final["evidence"]:
        lines.append(f"- {e}")
    lines.extend([
        "",
        "## Ranked Roadmap",
        "",
    ])
    for opt in roadmap["options"]:
        lines.append(
            f"### Option {opt['rank']} — {opt['role'].replace('_', ' ').title()}"
        )
        lines.append(f"- **Architecture:** {opt['name']} (`{opt['architecture_id']}`)")
        lines.append(f"- **Balance score:** {opt['composite_balance']}")
        lines.append(f"- **Performance score:** {opt['performance_score']}")
        lines.append(f"- **Engineering cost score:** {opt['engineering_cost_score']}")
        lines.append(f"- **Compatibility:** {opt['compatibility_overall']}")
        lines.append(f"- **Mean risk:** {opt['mean_risk']}")
        lines.append(f"- {opt['rationale']}")
        lines.append("")
    lines.extend([
        "## Constraints",
        "",
        f"- {final['range_engine_guarantee']}",
        f"- {final['why_not_keep_rf']}",
        f"- {final['why_not_lightgbm_first']}",
        f"- {final['why_not_stacked_first']}",
        "",
        f"**Next:** {final['next_phase_recommendation']}",
        "",
        "_Read-only blueprint. No production models implemented._",
        "",
    ])
    return "\n".join(lines)
