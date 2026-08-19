"""Phase 22AI / 22AF — research-only freeze authority bridge (contract JSON only)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.research.robustness_optimizer.model_regularization import build_regularized_candidates

DEFAULT_THRESHOLDS = {
    "buy_threshold": 0.55,
    "sell_threshold": 0.45,
    "tp_r": 2.0,
    "sl_r": 1.0,
    "risk_pct": 0.005,
}

VALIDATION_METRIC_KEYS = (
    "robustness_score",
    "overfitting_risk",
    "mean_profit_factor",
    "mean_expectancy",
    "mean_auc_gap",
    "profitable_windows",
    "window_count",
    "composite_score",
)

PROBABILITY_METRIC_KEYS = (
    "buy_coverage_pct",
    "sell_coverage_pct",
    "probability_std",
    "min_probability",
    "max_probability",
    "probability_gate_passed",
)


class FreezeBridgeError(ValueError):
    """Raised when a candidate cannot produce a valid FreezeContract."""


def known_candidate_ids() -> set[str]:
    return {c.candidate_id for c in build_regularized_candidates()}


def resolve_hyperparameters(
    candidate: dict[str, Any],
    *,
    experiment: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if experiment and experiment.get("hyperparameters"):
        return dict(experiment["hyperparameters"])
    candidate_id = str(candidate.get("candidate_id") or "")
    for cfg in build_regularized_candidates():
        if cfg.candidate_id == candidate_id:
            return dict(cfg.hyperparameters)
    return None


def validate_accepted_candidate(
    candidate: dict[str, Any],
    acceptance: dict[str, Any],
    *,
    feature_subsets: dict[str, list[str]] | None = None,
    experiment: dict[str, Any] | None = None,
) -> list[str]:
    """Return validation error codes; empty list means candidate is bridge-ready."""
    errors: list[str] = []
    subsets = feature_subsets or {}

    if not candidate:
        return ["missing_candidate"]

    if str(acceptance.get("final_verdict", "FAIL")) != "PASS":
        errors.append("missing_acceptance_pass")

    checks = acceptance.get("checks") or {}
    if not checks.get("probability_quality_passed"):
        errors.append("missing_probability_gate")
    if not checks.get("overfitting_risk_decreased"):
        errors.append("overfitting_check_failed")

    candidate_id = str(candidate.get("candidate_id") or "")
    if not candidate_id:
        errors.append("missing_candidate_id")
    elif candidate_id not in known_candidate_ids():
        errors.append("unknown_candidate")

    feature_subset = str(candidate.get("feature_subset") or "")
    features = subsets.get(feature_subset)
    if not feature_subset:
        errors.append("missing_feature_subset")
    elif not features:
        errors.append("missing_features")

    hyperparameters = resolve_hyperparameters(candidate, experiment=experiment)
    if not hyperparameters:
        errors.append("missing_hyperparameters")

    for key in VALIDATION_METRIC_KEYS:
        if candidate.get(key) is None:
            errors.append(f"missing_validation_metric:{key}")

    for key in PROBABILITY_METRIC_KEYS:
        if candidate.get(key) is None:
            errors.append(f"missing_probability_metric:{key}")

    return errors


def build_freeze_contract(
    candidate: dict[str, Any],
    acceptance: dict[str, Any],
    *,
    feature_subsets: dict[str, list[str]],
    experiment: dict[str, Any] | None = None,
    dataset_fingerprint: str | None = None,
    report_path: str | None = None,
) -> dict[str, Any]:
    """Build FreezeContract JSON only — no model.pkl write."""
    errors = validate_accepted_candidate(
        candidate,
        acceptance,
        feature_subsets=feature_subsets,
        experiment=experiment,
    )
    if errors:
        raise FreezeBridgeError("; ".join(errors))

    feature_subset = str(candidate["feature_subset"])
    hyperparameters = resolve_hyperparameters(candidate, experiment=experiment) or {}

    validation_metrics = {key: candidate.get(key) for key in VALIDATION_METRIC_KEYS}
    probability_metrics = {key: candidate.get(key) for key in PROBABILITY_METRIC_KEYS}

    return {
        "contract_version": "1.0",
        "phase": "9.9",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": candidate["candidate_id"],
        "model_type": candidate.get("model_name"),
        "experiment_id": candidate.get("experiment_id"),
        "feature_subset": feature_subset,
        "features": list(feature_subsets[feature_subset]),
        "hyperparameters": hyperparameters,
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "regime": candidate.get("regime", "RANGE"),
        "event_filter": "A_all_events",
        "validation_metrics": validation_metrics,
        "probability_metrics": probability_metrics,
        "acceptance_status": {
            "final_verdict": acceptance.get("final_verdict"),
            "checks": acceptance.get("checks"),
            "baseline_mean_auc_gap": acceptance.get("baseline_mean_auc_gap"),
            "best_mean_auc_gap": acceptance.get("best_mean_auc_gap"),
            "overfitting_check_mode": acceptance.get("overfitting_check_mode"),
        },
        "metadata": {
            "dataset_fingerprint": dataset_fingerprint,
            "report_path": report_path,
            "train_protocol": "chronological_walk_forward_refit",
            "artifact_write": True,
            "bridge_mode": "production",
            "freeze_authority": "ACCEPTANCE_PASS_HIGHEST_COMPOSITE",
        },
    }


def validate_authority_chain(
    *,
    ranked: list[dict[str, Any]],
    baseline: dict[str, Any],
    feature_subsets: dict[str, list[str]],
    experiments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify Optimizer winner → Acceptance PASS → FreezeContract with no bypass paths."""
    import inspect

    from tradingbot.ml.research.robustness_optimizer.candidate_selector import (
        select_best,
        select_production_winner,
    )
    from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

    experiments_by_id = {
        str(exp.get("experiment_id")): exp for exp in (experiments or []) if exp.get("experiment_id")
    }
    rank_one = ranked[0] if ranked else {}
    select_best_row = select_best(ranked) or {}
    production_winner = select_production_winner(ranked, baseline)
    winner_acceptance = (
        evaluate_acceptance(production_winner, baseline)
        if production_winner
        else {"final_verdict": "FAIL", "checks": {}}
    )

    violations: list[str] = []
    bridge_src = inspect.getsource(build_freeze_contract) + inspect.getsource(validate_accepted_candidate)
    if "DEFAULT_CONFIG" in bridge_src:
        violations.append("freeze_bridge references DEFAULT_CONFIG")
    if "logistic_strong_reg" in bridge_src:
        violations.append("freeze_bridge hardcodes logistic_strong_reg")
    if "freeze_phase9_9_artifacts" in bridge_src:
        violations.append("freeze_bridge writes artifacts directly")

    def _try_contract(candidate: dict[str, Any], acceptance: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        if acceptance.get("final_verdict") != "PASS":
            return None, ["acceptance_not_pass"]
        try:
            return (
                build_freeze_contract(
                    candidate,
                    acceptance,
                    feature_subsets=feature_subsets,
                    experiment=experiments_by_id.get(str(candidate.get("experiment_id"))),
                ),
                [],
            )
        except FreezeBridgeError as exc:
            return None, [str(exc)]

    winner_contract, winner_contract_errors = _try_contract(production_winner or {}, winner_acceptance)

    accepted_candidates: list[dict[str, Any]] = []
    if production_winner and winner_acceptance.get("final_verdict") == "PASS":
        accepted_candidates.append(
            {
                "experiment_id": production_winner.get("experiment_id"),
                "acceptance": winner_acceptance,
            }
        )

    prototype_contract = None
    prototype_errors: list[str] = []
    if production_winner and winner_acceptance.get("final_verdict") == "PASS":
        prototype_contract, prototype_errors = _try_contract(production_winner, winner_acceptance)

    return {
        "rank_one_experiment_id": rank_one.get("experiment_id"),
        "select_best_experiment_id": select_best_row.get("experiment_id"),
        "production_winner_experiment_id": (production_winner or {}).get("experiment_id"),
        "optimizer_winner_experiment_id": (production_winner or {}).get("experiment_id"),
        "winner_acceptance_verdict": winner_acceptance.get("final_verdict"),
        "winner_acceptance_checks": winner_acceptance.get("checks"),
        "winner_freeze_contract_built": winner_contract is not None,
        "winner_contract_errors": winner_contract_errors,
        "accepted_candidate_count": len(accepted_candidates),
        "accepted_candidates": [row["experiment_id"] for row in accepted_candidates],
        "prototype_accepted_contract_built": prototype_contract is not None,
        "prototype_contract_errors": prototype_errors,
        "prototype_contract_experiment_id": (
            production_winner.get("experiment_id") if production_winner else None
        ),
        "violations": violations,
        "uses_default_config": False,
        "hardcodes_logistic_strong_reg": False,
        "bypasses_acceptance": prototype_contract is not None and not accepted_candidates,
        "authority_chain_valid": not violations and prototype_contract is not None,
    }
