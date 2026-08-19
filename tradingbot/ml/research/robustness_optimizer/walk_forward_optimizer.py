"""Phase 9.9 — walk-forward experiments for robustness candidates."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.robustness_optimizer.model_regularization import ModelCandidateConfig
from tradingbot.ml.research.robustness_optimizer.probability_selection_gate import (
    aggregate_experiment_probability_metrics,
    evaluate_probability_gate,
)
from tradingbot.ml.research.robustness_optimizer.window_validator import validate_window_candidate
from tradingbot.ml.research.walk_forward.robustness_analyzer import analyze_robustness
from tradingbot.ml.research.walk_forward.walk_forward_metrics import aggregate_window_metrics
from tradingbot.ml.research.walk_forward.window_manager import (
    WalkForwardWindow,
    build_standard_windows,
    partition_window,
)
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)


def run_walk_forward_experiment(
    df: pd.DataFrame,
    *,
    candidate: ModelCandidateConfig,
    feature_cols: list[str],
    regime: str = "RANGE",
    event_scheme: str = "A_all_events",
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Expanding walk-forward for one model + feature + regime configuration."""
    np.random.seed(seed)
    windows = build_standard_windows(df)
    results: list[dict[str, Any]] = []

    for window in windows:
        train_df, val_df = partition_window(df, window)
        result = validate_window_candidate(
            train_df,
            val_df,
            window,
            candidate=candidate,
            feature_cols=feature_cols,
            seed=seed,
            regime=regime,
            event_scheme=event_scheme,
        )
        results.append(result)

    active = [r for r in results if not r.get("skipped")]
    aggregate = aggregate_window_metrics(active)
    robustness = analyze_robustness(active, aggregate)

    profitable_windows = sum(1 for w in active if float(w.get("profit_factor", 0.0) or 0.0) >= 1.0)

    probability_audits = [w["probability_audit"] for w in active if w.get("probability_audit")]
    probability_metrics = aggregate_experiment_probability_metrics(probability_audits)
    probability_gate = evaluate_probability_gate(probability_metrics)

    return {
        "candidate_id": candidate.candidate_id,
        "model_name": candidate.model_name,
        "hyperparameters": candidate.hyperparameters,
        "feature_cols": feature_cols,
        "regime": regime,
        "event_scheme": event_scheme,
        "window_count": len(active),
        "profitable_windows": profitable_windows,
        "windows": results,
        "aggregate": aggregate,
        "robustness": robustness,
        "robustness_score": robustness.get("robustness_score", 0.0),
        "overfitting_risk": robustness.get("overfitting_risk", "HIGH"),
        "mean_profit_factor": robustness.get("mean_profit_factor", 0.0),
        "mean_expectancy": robustness.get("mean_expectancy", 0.0),
        "mean_auc_gap": robustness.get("train_test_gap", {}).get("mean_auc_gap", 0.0),
        "probability_metrics": probability_metrics,
        "probability_gate": probability_gate,
        "shuffle": False,
    }


def run_candidate_grid(
    df: pd.DataFrame,
    candidates: list[ModelCandidateConfig],
    feature_subsets: dict[str, list[str]],
    *,
    regimes: list[str] | None = None,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """Run walk-forward for each model × feature subset × regime."""
    target_regimes = regimes or ["RANGE"]
    experiments: list[dict[str, Any]] = []

    for candidate in candidates:
        for subset_name, features in feature_subsets.items():
            if not features:
                continue
            for regime in target_regimes:
                exp_id = f"{candidate.candidate_id}__{subset_name}__{regime}"
                logger.info("Phase 9.9 experiment: %s", exp_id)
                try:
                    result = run_walk_forward_experiment(
                        df,
                        candidate=candidate,
                        feature_cols=features,
                        regime=regime,
                        seed=seed,
                    )
                    result["experiment_id"] = exp_id
                    result["feature_subset"] = subset_name
                    experiments.append(result)
                except Exception as exc:
                    experiments.append(
                        {
                            "experiment_id": exp_id,
                            "candidate_id": candidate.candidate_id,
                            "feature_subset": subset_name,
                            "regime": regime,
                            "error": str(exc),
                            "skipped": True,
                        }
                    )
    return experiments
