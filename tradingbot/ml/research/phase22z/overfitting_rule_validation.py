"""Phase 22Z — overfitting_risk_decreased acceptance rule validation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

HIGH_GAP_THRESHOLD = 0.12
MEDIUM_GAP_THRESHOLD = 0.06
HIGH_DEGRADATION_THRESHOLD = 0.25
MEDIUM_DEGRADATION_THRESHOLD = 0.12
HIGH_ROBUSTNESS_THRESHOLD = 45
MEDIUM_ROBUSTNESS_THRESHOLD = 70


def load_baseline_numeric(phase98_robustness: dict[str, Any], phase98_windows: dict[str, Any]) -> dict[str, Any]:
    windows = [w for w in phase98_windows.get("windows", []) if not w.get("skipped")]
    degradations = [float(w.get("performance_degradation", 0.0) or 0.0) for w in windows]
    mean_degradation = round(sum(degradations) / len(degradations), 6) if degradations else None
    train_test = phase98_robustness.get("train_test_gap") or {}
    return {
        "robustness_score": float(phase98_robustness.get("robustness_score", 0.0) or 0.0),
        "overfitting_risk": str(phase98_robustness.get("overfitting_risk", "HIGH")),
        "mean_profit_factor": float(phase98_robustness.get("mean_profit_factor", 0.0) or 0.0),
        "mean_expectancy": float(phase98_robustness.get("mean_expectancy", 0.0) or 0.0),
        "mean_auc_gap": float(train_test.get("mean_auc_gap", 0.0) or 0.0),
        "max_auc_gap": float(train_test.get("max_auc_gap", 0.0) or 0.0),
        "mean_degradation": mean_degradation,
        "degradation_per_window": degradations,
        "source_robustness_report": "data/ml/reports/phase9_8_robustness_report.json",
        "source_window_results": "data/ml/reports/phase9_8_window_results.json",
    }


def _ordinal_overfitting_pass(candidate_risk: str, baseline_risk: str) -> bool:
    return RISK_ORDER.get(candidate_risk, 2) < RISK_ORDER.get(baseline_risk, 2)


def _numeric_auc_gap_better(candidate_gap: float, baseline_gap: float) -> bool:
    return candidate_gap < baseline_gap


def _explain_high_label(gap: float, robustness: float, *, degradation: float | None) -> list[str]:
    triggers: list[str] = []
    if gap > HIGH_GAP_THRESHOLD:
        triggers.append(f"mean_auc_gap>{HIGH_GAP_THRESHOLD}")
    if robustness < HIGH_ROBUSTNESS_THRESHOLD:
        triggers.append(f"robustness_score<{HIGH_ROBUSTNESS_THRESHOLD}")
    if degradation is not None and degradation > HIGH_DEGRADATION_THRESHOLD:
        triggers.append(f"mean_degradation>{HIGH_DEGRADATION_THRESHOLD}")
    return triggers


def classify_overfitting_rejection(
    candidate: dict[str, Any],
    baseline_numeric: dict[str, Any],
    baseline_acceptance: dict[str, Any],
) -> dict[str, Any]:
    baseline = baseline_acceptance.get("baseline") or {}
    checks = evaluate_acceptance(candidate, baseline)["checks"]
    gap = float(candidate.get("mean_auc_gap", 0.0) or 0.0)
    base_gap = float(baseline_numeric["mean_auc_gap"])
    risk = str(candidate.get("overfitting_risk", "HIGH"))
    base_risk = str(baseline_numeric["overfitting_risk"])
    robustness = float(candidate.get("robustness_score", 0.0) or 0.0)
    degradation = candidate.get("mean_degradation")

    ordinal_pass = bool(checks.get("overfitting_risk_decreased"))
    numeric_gap_better = _numeric_auc_gap_better(gap, base_gap)

    if ordinal_pass:
        rejection_category = None
        rejection_reason = "overfitting_risk_decreased_passed"
    elif not numeric_gap_better:
        rejection_category = "Rejected because: really Overfit"
        rejection_reason = (
            f"mean_auc_gap={gap} is not lower than baseline={base_gap}; "
            "candidate is not numerically better on train/validation AUC gap"
        )
    elif risk == base_risk and numeric_gap_better:
        rejection_category = "Rejected because: Label Logic"
        rejection_reason = (
            f"mean_auc_gap improved ({gap} < {base_gap}) but ordinal label unchanged "
            f"({risk} vs baseline {base_risk}); assess_overfitting_risk buckets both as HIGH"
        )
    elif numeric_gap_better and not ordinal_pass:
        rejection_category = "Rejected because: Label Logic"
        rejection_reason = (
            f"numeric mean_auc_gap improved ({gap} < {base_gap}) but ordinal "
            f"overfitting_risk_decreased failed ({risk} vs baseline {base_risk})"
        )
    else:
        rejection_category = "Rejected because: really Overfit"
        rejection_reason = "failed numeric and ordinal overfitting comparison"

    return {
        "experiment_id": candidate.get("experiment_id"),
        "overfitting_risk_decreased_passed": ordinal_pass,
        "rejection_category": rejection_category,
        "rejection_reason": rejection_reason,
        "candidate_overfitting_risk": risk,
        "baseline_overfitting_risk": base_risk,
        "mean_auc_gap": gap,
        "baseline_mean_auc_gap": base_gap,
        "mean_auc_gap_delta_vs_baseline": round(base_gap - gap, 6),
        "numeric_auc_gap_better_than_baseline": numeric_gap_better,
        "mean_degradation": degradation if degradation is not None else "NOT_STORED_IN_PHASE9_9_RANKING_JSON",
        "high_label_triggers_if_applicable": _explain_high_label(
            gap,
            robustness,
            degradation=float(degradation) if isinstance(degradation, (int, float)) else None,
        ),
    }


def build_candidate_metrics(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        acceptance = evaluate_acceptance(candidate, baseline)
        rows.append(
            {
                "experiment_id": candidate.get("experiment_id"),
                "model": candidate.get("model_name"),
                "feature_subset": candidate.get("feature_subset"),
                "composite_score": candidate.get("composite_score"),
                "mean_profit_factor": candidate.get("mean_profit_factor"),
                "robustness_score": candidate.get("robustness_score"),
                "mean_expectancy": candidate.get("mean_expectancy"),
                "probability_gate_passed": candidate.get("probability_gate_passed"),
                "acceptance_result": acceptance["final_verdict"],
                "acceptance_checks": acceptance["checks"],
                "overfitting_risk": candidate.get("overfitting_risk"),
                "mean_auc_gap": candidate.get("mean_auc_gap"),
                "mean_degradation": candidate.get("mean_degradation", "NOT_STORED_IN_PHASE9_9_RANKING_JSON"),
            }
        )
    return rows


def run_validation(
    comparison: dict[str, Any],
    *,
    phase98_robustness: dict[str, Any],
    phase98_windows: dict[str, Any],
) -> dict[str, Any]:
    ranked = comparison.get("ranked_candidates") or []
    baseline = comparison.get("baseline_phase9_8") or {}
    baseline_numeric = load_baseline_numeric(phase98_robustness, phase98_windows)

    candidate_metrics = build_candidate_metrics(ranked, baseline)
    rejection_rows = [
        classify_overfitting_rejection(c, baseline_numeric, {"baseline": baseline}) for c in ranked
    ]

    ordinal_pass = [r for r in rejection_rows if r["overfitting_risk_decreased_passed"]]
    label_logic = [r for r in rejection_rows if r["rejection_category"] == "Rejected because: Label Logic"]
    really_overfit = [r for r in rejection_rows if r["rejection_category"] == "Rejected because: really Overfit"]

    numeric_gap_better = [r for r in rejection_rows if r["numeric_auc_gap_better_than_baseline"]]

    gate_passed = [c for c in ranked if c.get("probability_gate_passed")]
    gate_passed_rejections = [
        classify_overfitting_rejection(c, baseline_numeric, {"baseline": baseline}) for c in gate_passed
    ]

    rule_stats = {
        "total_candidates": len(ranked),
        "overfitting_risk_decreased_pass": len(ordinal_pass),
        "overfitting_risk_decreased_fail": len(ranked) - len(ordinal_pass),
        "fail_really_overfit": len(really_overfit),
        "fail_label_logic": len(label_logic),
        "numeric_mean_auc_gap_better_than_baseline": len(numeric_gap_better),
        "numeric_mean_auc_gap_not_better": len(ranked) - len(numeric_gap_better),
        "probability_gate_passed_fail_overfitting_ordinal": sum(
            1 for r in gate_passed_rejections if not r["overfitting_risk_decreased_passed"]
        ),
    }

    simulation = {
        "note": (
            "mean_degradation is not persisted in phase9_9_model_comparison.json; "
            "numeric analysis uses mean_auc_gap vs Phase 9.8 baseline only"
        ),
        "baseline_mean_auc_gap": baseline_numeric["mean_auc_gap"],
        "baseline_mean_degradation": baseline_numeric["mean_degradation"],
        "candidates_with_lower_mean_auc_gap": len(numeric_gap_better),
        "candidates_with_equal_or_higher_mean_auc_gap": len(ranked) - len(numeric_gap_better),
        "candidates_passing_ordinal_overfitting_risk_decreased": len(ordinal_pass),
        "candidates_failing_despite_lower_mean_auc_gap": len(label_logic),
    }

    verdict = determine_verdict(rule_stats, label_logic, really_overfit, gate_passed_rejections)

    return {
        "candidate_overfitting_metrics": {
            "baseline_numeric": baseline_numeric,
            "candidates": candidate_metrics,
        },
        "baseline_comparison": {
            "baseline_phase9_8_summary": baseline,
            "baseline_numeric": baseline_numeric,
            "per_candidate_vs_baseline": [
                {
                    "experiment_id": r["experiment_id"],
                    "robustness_delta": round(
                        float(next(c for c in ranked if c["experiment_id"] == r["experiment_id"])["robustness_score"])
                        - baseline_numeric["robustness_score"],
                        4,
                    ),
                    "mean_auc_gap_delta": r["mean_auc_gap_delta_vs_baseline"],
                    "numeric_auc_gap_better": r["numeric_auc_gap_better_than_baseline"],
                    "candidate_risk": r["candidate_overfitting_risk"],
                    "baseline_risk": r["baseline_overfitting_risk"],
                    "ordinal_overfitting_pass": r["overfitting_risk_decreased_passed"],
                    "same_label_as_baseline": r["candidate_overfitting_risk"] == r["baseline_overfitting_risk"],
                }
                for r in rejection_rows
            ],
            "finding": (
                f"{len(numeric_gap_better)}/{len(ranked)} candidates have lower mean_auc_gap than Phase 9.8, "
                f"but {len(label_logic)} still fail overfitting_risk_decreased because the ordinal HIGH label "
                f"did not improve even when numeric gap improved."
            ),
        },
        "overfitting_numeric_analysis": simulation,
        "rule_correctness_report": {
            "rule": "overfitting_risk_decreased",
            "implementation": {
                "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                "function": "evaluate_acceptance / _risk_improved",
                "formula": "order[candidate_risk] < order[baseline_risk]",
                "risk_order": RISK_ORDER,
            },
            "label_source": {
                "file": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                "function": "assess_overfitting_risk",
                "thresholds": {
                    "HIGH": f"mean_gap>{HIGH_GAP_THRESHOLD} OR robustness<{HIGH_ROBUSTNESS_THRESHOLD} OR mean_degradation>{HIGH_DEGRADATION_THRESHOLD}",
                    "MEDIUM": f"mean_gap>{MEDIUM_GAP_THRESHOLD} OR robustness<{MEDIUM_ROBUSTNESS_THRESHOLD} OR mean_degradation>{MEDIUM_DEGRADATION_THRESHOLD}",
                    "LOW": "otherwise",
                },
            },
            "statistics": rule_stats,
            "is_too_strict_evidence": {
                "baseline_is_high_risk": baseline_numeric["overfitting_risk"] == "HIGH",
                "candidates_numeric_gap_better_but_ordinal_fail": len(label_logic),
                "gate_passed_all_fail_ordinal": all(
                    not r["overfitting_risk_decreased_passed"] for r in gate_passed_rejections
                ),
                "example": label_logic[0] if label_logic else None,
            },
        },
        "candidate_rejection_reason": {
            "candidates": rejection_rows,
            "summary": {
                "pass_overfitting_risk_decreased": len(ordinal_pass),
                "rejected_really_overfit": len(really_overfit),
                "rejected_label_logic": len(label_logic),
            },
        },
        "verdict": verdict,
    }


def determine_verdict(
    rule_stats: dict[str, Any],
    label_logic: list[dict[str, Any]],
    really_overfit: list[dict[str, Any]],
    gate_passed_rejections: list[dict[str, Any]],
) -> str:
    total = int(rule_stats["total_candidates"])
    label_fail = int(rule_stats["fail_label_logic"])
    actual_fail = int(rule_stats["fail_really_overfit"])

    if label_fail >= total // 2 and actual_fail <= 1:
        return "RULE_TOO_STRICT"

    if actual_fail > label_fail:
        return "RULE_CORRECT"

    if label_fail == 0 and actual_fail == 0:
        return "RULE_CORRECT"

    if gate_passed_rejections and all(not r["overfitting_risk_decreased_passed"] for r in gate_passed_rejections):
        if label_fail >= len(gate_passed_rejections):
            return "RULE_TOO_STRICT"

    if label_fail > 0 and actual_fail == 0:
        return "RULE_TOO_STRICT"

    return "UNKNOWN"
