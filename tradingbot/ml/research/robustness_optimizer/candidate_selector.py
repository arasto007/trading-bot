"""Phase 9.9 — rank robustness candidates."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
PRODUCTION_WINNER_RULE = "ACCEPTANCE_PASS_HIGHEST_COMPOSITE"


def _experiment_probability_fields(exp: dict[str, Any]) -> dict[str, Any]:
    metrics = exp.get("probability_metrics") or {}
    gate = exp.get("probability_gate") or {}
    return {
        "buy_coverage_pct": metrics.get("buy_coverage_pct"),
        "sell_coverage_pct": metrics.get("sell_coverage_pct"),
        "min_probability": metrics.get("min_probability"),
        "max_probability": metrics.get("max_probability"),
        "probability_std": metrics.get("std"),
        "probability_histogram": metrics.get("histogram"),
        "probability_gate_passed": bool(gate.get("passed", False)),
        "acceptance_reason": gate.get("acceptance_reason"),
        "rejection_reason": gate.get("rejection_reason"),
    }


def overfitting_penalty(experiment: dict[str, Any]) -> float:
    gap = float(experiment.get("mean_auc_gap", 0.0) or 0.0)
    degradation = float(
        experiment.get("robustness", {})
        .get("overfitting_indicators", {})
        .get("high_auc_gap_windows", 0)
    )
    return min(1.0, gap * 3.0 + degradation * 0.05)


def expectancy_consistency(experiment: dict[str, Any]) -> float:
    std_exp = float(
        experiment.get("aggregate", {})
        .get("stability_score", {})
        .get("std_expectancy", 0.0)
        or 0.0
    )
    return round(1.0 / (1.0 + std_exp), 4)


def composite_score(experiment: dict[str, Any]) -> float:
    """Higher is better: robustness, PF, consistency, low overfitting."""
    if experiment.get("skipped") or experiment.get("error"):
        return -1.0

    robustness = float(experiment.get("robustness_score", 0.0) or 0.0) / 100.0
    mean_pf = float(experiment.get("mean_profit_factor", 0.0) or 0.0)
    pf_norm = min(1.0, mean_pf / 2.0)
    consistency = expectancy_consistency(experiment)
    penalty = overfitting_penalty(experiment)

    return round(
        0.40 * robustness + 0.25 * pf_norm + 0.20 * consistency + 0.15 * (1.0 - penalty),
        6,
    )


def rank_candidates(experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank experiments by composite score with overfitting penalty."""
    ranked: list[dict[str, Any]] = []
    for exp in experiments:
        if exp.get("skipped") or exp.get("error"):
            continue
        prob_fields = _experiment_probability_fields(exp)
        ranked.append(
            {
                "experiment_id": exp.get("experiment_id"),
                "candidate_id": exp.get("candidate_id"),
                "model_name": exp.get("model_name"),
                "feature_subset": exp.get("feature_subset"),
                "regime": exp.get("regime"),
                "robustness_score": exp.get("robustness_score"),
                "overfitting_risk": exp.get("overfitting_risk"),
                "mean_profit_factor": exp.get("mean_profit_factor"),
                "mean_expectancy": exp.get("mean_expectancy"),
                "mean_auc_gap": exp.get("mean_auc_gap"),
                "profitable_windows": exp.get("profitable_windows"),
                "window_count": exp.get("window_count"),
                "composite_score": composite_score(exp),
                "expectancy_consistency": expectancy_consistency(exp),
                "overfitting_penalty": round(overfitting_penalty(exp), 4),
                **prob_fields,
            }
        )

    def sort_key(row: dict[str, Any]) -> tuple[int, float, float, float, int]:
        gate_failed = 0 if row.get("probability_gate_passed") else 1
        risk = RISK_ORDER.get(str(row.get("overfitting_risk", "HIGH")), 2)
        return (
            gate_failed,
            -float(row.get("composite_score", 0.0)),
            -float(row.get("robustness_score", 0.0)),
            risk,
            -int(row.get("profitable_windows", 0)),
        )

    return sorted(ranked, key=sort_key)


def select_best(ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in ranked:
        if row.get("probability_gate_passed"):
            return row
    return None


def select_production_winner(
    ranked: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any] | None:
    """Production authority: highest composite among acceptance + probability gate pass."""
    eligible: list[dict[str, Any]] = []
    for candidate in ranked:
        if not candidate.get("probability_gate_passed"):
            continue
        acceptance = evaluate_acceptance(candidate, baseline)
        if acceptance.get("final_verdict") == "PASS":
            eligible.append(candidate)
    if not eligible:
        return None
    return max(eligible, key=lambda row: float(row.get("composite_score", 0.0) or 0.0))
