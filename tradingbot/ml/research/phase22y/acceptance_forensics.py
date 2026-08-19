"""Phase 22Y — accepted candidate failure forensics."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

ACCEPTANCE_RULES = (
    "robustness_improved",
    "overfitting_risk_decreased",
    "mean_expectancy_positive",
    "profitable_windows_ge_4",
    "probability_quality_passed",
)

FAILED_RULE_LABELS = {
    "robustness_improved": "robustness_failed",
    "overfitting_risk_decreased": "overfitting_risk_failed",
    "mean_expectancy_positive": "expectancy_failed",
    "profitable_windows_ge_4": "profitable_windows_failed",
    "probability_quality_passed": "probability_quality_failed",
}


def _failed_rules(checks: dict[str, bool]) -> list[str]:
    return [FAILED_RULE_LABELS[rule] for rule in ACCEPTANCE_RULES if not checks.get(rule, False)]


def _passed_rules(checks: dict[str, bool]) -> list[str]:
    return [rule for rule in ACCEPTANCE_RULES if checks.get(rule, False)]


def _candidate_summary(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    acceptance = evaluate_acceptance(candidate, baseline)
    checks = acceptance["checks"]
    return {
        "experiment_id": candidate.get("experiment_id"),
        "model": candidate.get("model_name"),
        "feature_subset": candidate.get("feature_subset"),
        "composite_score": candidate.get("composite_score"),
        "mean_profit_factor": candidate.get("mean_profit_factor"),
        "win_rate": "NOT_STORED_IN_PHASE9_9_RANKING_JSON",
        "mean_expectancy": candidate.get("mean_expectancy"),
        "robustness_score": candidate.get("robustness_score"),
        "overfitting_risk": candidate.get("overfitting_risk"),
        "profitable_windows": candidate.get("profitable_windows"),
        "window_count": candidate.get("window_count"),
        "probability_metrics": {
            "buy_coverage_pct": candidate.get("buy_coverage_pct"),
            "sell_coverage_pct": candidate.get("sell_coverage_pct"),
            "min_probability": candidate.get("min_probability"),
            "max_probability": candidate.get("max_probability"),
            "probability_std": candidate.get("probability_std"),
            "histogram_total": (candidate.get("probability_histogram") or {}).get("total"),
        },
        "probability_gate_passed": candidate.get("probability_gate_passed"),
        "acceptance_status": acceptance["final_verdict"],
        "acceptance_checks": checks,
        "failed_rules": _failed_rules(checks),
        "passed_rules": _passed_rules(checks),
    }


def rule_failure_statistics(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    scope: str,
) -> dict[str, Any]:
    stats: dict[str, dict[str, int]] = {
        rule: {"passed": 0, "failed": 0} for rule in ACCEPTANCE_RULES
    }
    for candidate in candidates:
        checks = evaluate_acceptance(candidate, baseline)["checks"]
        for rule in ACCEPTANCE_RULES:
            if checks.get(rule):
                stats[rule]["passed"] += 1
            else:
                stats[rule]["failed"] += 1

    ranked = sorted(
        (
            {
                "rule": rule,
                "failed_label": FAILED_RULE_LABELS[rule],
                "passed": stats[rule]["passed"],
                "failed": stats[rule]["failed"],
                "failure_rate_pct": round(stats[rule]["failed"] / max(len(candidates), 1) * 100, 4),
            }
            for rule in ACCEPTANCE_RULES
        ),
        key=lambda row: (-row["failed"], row["rule"]),
    )
    return {
        "scope": scope,
        "candidate_count": len(candidates),
        "rules": ranked,
        "dominant_rule": ranked[0] if ranked else None,
    }


def simulate_ignore_single_rule(
    candidates: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    scope: str,
) -> dict[str, Any]:
    simulations: list[dict[str, Any]] = []
    for ignored_rule in ACCEPTANCE_RULES:
        accepted: list[str] = []
        for candidate in candidates:
            checks = dict(evaluate_acceptance(candidate, baseline)["checks"])
            checks[ignored_rule] = True
            if all(checks.values()):
                accepted.append(str(candidate.get("experiment_id")))
        simulations.append(
            {
                "ignored_rule": ignored_rule,
                "ignored_failed_label": FAILED_RULE_LABELS[ignored_rule],
                "accepted_count": len(accepted),
                "accepted_experiment_ids": accepted,
            }
        )

    simulations.sort(key=lambda row: -row["accepted_count"])
    return {
        "scope": scope,
        "candidate_count": len(candidates),
        "simulations": simulations,
        "best_single_rule_relaxation": simulations[0] if simulations else None,
    }


def run_forensics(
    comparison: dict[str, Any],
    *,
    robustness_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ranked = comparison.get("ranked_candidates") or []
    baseline = comparison.get("baseline_phase9_8") or {}
    if robustness_report and not baseline:
        baseline = robustness_report.get("baseline_phase9_8") or {}

    gate_passed = [c for c in ranked if c.get("probability_gate_passed")]
    accepted_summaries = [_candidate_summary(c, baseline) for c in gate_passed]

    all_stats = rule_failure_statistics(ranked, baseline, scope="all_ranked_candidates")
    gate_stats = rule_failure_statistics(gate_passed, baseline, scope="probability_gate_passed_only")

    gate_simulation = simulate_ignore_single_rule(gate_passed, baseline, scope="probability_gate_passed_only")
    all_simulation = simulate_ignore_single_rule(ranked, baseline, scope="all_ranked_candidates")

    dominant = gate_stats["dominant_rule"] or {}
    dominant_rule = dominant.get("rule", "")

    return {
        "accepted_candidates": {
            "count": len(gate_passed),
            "baseline_phase9_8": baseline,
            "candidates": accepted_summaries,
        },
        "acceptance_breakdown": {
            "probability_gate_passed_count": len(gate_passed),
            "final_verdict_failures": [
                {
                    "experiment_id": row["experiment_id"],
                    "failed_rules": row["failed_rules"],
                    "passed_rules": row["passed_rules"],
                    "acceptance_status": row["acceptance_status"],
                }
                for row in accepted_summaries
            ],
        },
        "rule_failure_statistics": {
            "all_ranked_candidates": all_stats,
            "probability_gate_passed_only": gate_stats,
        },
        "dominant_rejection_rule": {
            "scope": "probability_gate_passed_only",
            "rule": dominant_rule,
            "failed_label": FAILED_RULE_LABELS.get(dominant_rule, dominant_rule),
            "failed_count": dominant.get("failed"),
            "candidate_count": len(gate_passed),
            "all_five_gate_passed_candidates_fail_this_rule": dominant.get("failed") == len(gate_passed),
            "evidence_source": "data/ml/reports/phase9_9_model_comparison.json",
        },
        "rule_origin_analysis": build_rule_origin_analysis(dominant_rule),
        "candidate_acceptance_simulation": {
            "probability_gate_passed_only": gate_simulation,
            "all_ranked_candidates": all_simulation,
        },
        "verdict": determine_verdict(dominant_rule, gate_stats, gate_simulation),
    }


def build_rule_origin_analysis(dominant_rule: str) -> dict[str, Any]:
    return {
        "dominant_rule": dominant_rule,
        "implementation": {
            "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "evaluate_acceptance",
            "helper": "_risk_improved" if dominant_rule == "overfitting_risk_decreased" else None,
            "formula": {
                "robustness_improved": "best.robustness_score > baseline.robustness_score",
                "overfitting_risk_decreased": "order[best_risk] < order[baseline_risk] where order={LOW:0,MEDIUM:1,HIGH:2}",
                "mean_expectancy_positive": "best.mean_expectancy > 0",
                "profitable_windows_ge_4": "best.profitable_windows >= 4 AND best.window_count >= 4",
                "probability_quality_passed": "best.probability_gate_passed is True (added Phase 22X)",
            },
            "constants": {
                "profitable_windows_minimum": 4,
                "window_count_minimum": 4,
                "risk_order": {"LOW": 0, "MEDIUM": 1, "HIGH": 2},
            },
            "overfitting_risk_label_source": {
                "file": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                "function": "assess_overfitting_risk",
                "thresholds": {
                    "HIGH": "mean_gap > 0.12 OR robustness_score < 45 OR mean_degradation > 0.25",
                    "MEDIUM": "mean_gap > 0.06 OR robustness_score < 70 OR mean_degradation > 0.12",
                    "LOW": "otherwise",
                },
            },
        },
        "origin": {
            "phase_introduced": "9.9",
            "designed_for_phase9_9": True,
            "inherited_from_phase9_8_acceptance": False,
            "phase9_8_verdict_logic": {
                "file": "tradingbot/ml/research/walk_forward/report_generator.py",
                "rule": "final_verdict PASS if active_windows >= 4 AND integrity.status == PASS",
                "note": "Phase 9.8 has no overfitting_risk_decreased or robustness_improved checks",
            },
            "phase9_9_intent": {
                "docstring": "Check Phase 9.9 acceptance vs Phase 9.8 baseline",
                "pattern": "Sequential phase improvement gate — candidate must beat Phase 9.8 baseline on multiple axes",
            },
            "conclusion": (
                "overfitting_risk_decreased was authored in Phase 9.9 evaluate_acceptance to require "
                "strict ordinal improvement over the Phase 9.8 baseline risk label. It was not copied "
                "from Phase 9.8 code (which lacks acceptance checks), but inherits the sequential "
                "baseline-beating pattern used across Phase 9.9 acceptance rules."
            ),
        },
    }


def determine_verdict(
    dominant_rule: str,
    gate_stats: dict[str, Any],
    gate_simulation: dict[str, Any],
) -> str:
    dominant = gate_stats.get("dominant_rule") or {}
    if not dominant:
        return "UNKNOWN"

    failed = int(dominant.get("failed", 0))
    total = int(gate_stats.get("candidate_count", 0))
    if total == 0:
        return "UNKNOWN"

    best_relax = gate_simulation.get("best_single_rule_relaxation") or {}
    accepted_if_ignored = int(best_relax.get("accepted_count", 0))

    if dominant_rule == "overfitting_risk_decreased" and failed == total:
        if accepted_if_ignored >= 1:
            return "ACCEPTANCE_RULE_TOO_STRICT"
    if dominant_rule == "probability_quality_passed":
        return "ACCEPTANCE_RULE_VALID"

    if failed == total and accepted_if_ignored >= 1:
        return "ACCEPTANCE_RULE_TOO_STRICT"

    if dominant_rule in {"robustness_improved", "overfitting_risk_decreased"} and failed == total:
        return "ACCEPTANCE_RULE_OUTDATED"

    return "ACCEPTANCE_RULE_VALID"
