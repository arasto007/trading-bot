"""Phase 22W — Phase 9.9 model-selection criterion root-cause verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRIMARY_VERDICT = "MODEL_SELECTION_CRITERIA"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_selection_pipeline_map() -> dict[str, Any]:
    return {
        "phase": "22W",
        "title": "Phase 9.9 model selection pipeline (repository trace)",
        "entry": {
            "orchestrator": "RobustnessOptimizer.run",
            "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
            "script": "scripts/train_model.py --phase9-9",
        },
        "stages": [
            {
                "order": 1,
                "name": "candidate_generation",
                "function": "build_regularized_candidates + run_candidate_grid",
                "files": [
                    "tradingbot/ml/research/robustness_optimizer/model_regularization.py",
                    "tradingbot/ml/research/robustness_optimizer/walk_forward_optimizer.py",
                ],
                "candidates": 7,
                "feature_subsets": 4,
                "regimes": ["RANGE"],
                "total_experiments": 28,
            },
            {
                "order": 2,
                "name": "per_window_train_validate",
                "function": "validate_window_candidate",
                "file": "tradingbot/ml/research/robustness_optimizer/window_validator.py",
                "metrics_computed": [
                    "roc_auc", "precision", "recall", "f1",
                    "train_roc_auc", "train_val_auc_gap", "performance_degradation",
                    "num_trades", "win_rate", "profit_factor", "expectancy",
                    "max_drawdown", "total_return", "sharpe_proxy",
                ],
                "trade_simulation": {
                    "file": "tradingbot/ml/research/walk_forward/model_validator.py",
                    "strategy": "ThresholdStrategy buy=0.55 sell=0.45",
                    "note": "PF/win_rate come from simulated trades on validation probabilities",
                },
            },
            {
                "order": 3,
                "name": "robustness_scoring",
                "function": "analyze_robustness / compute_robustness_score",
                "file": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                "robustness_formula": "100 * (0.30*pf_pass + 0.30*exp_pass + 0.25*consistency + 0.15*(1-gap_penalty))",
                "overfitting_risk": "from mean train_val_auc_gap and performance_degradation",
            },
            {
                "order": 4,
                "name": "candidate_ranking",
                "function": "rank_candidates / composite_score",
                "file": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
                "composite_weights": {
                    "robustness_score": 0.40,
                    "mean_profit_factor_normalized": 0.25,
                    "expectancy_consistency": 0.20,
                    "low_overfitting_penalty": 0.15,
                },
                "tie_breakers": ["composite_score", "robustness_score", "overfitting_risk", "profitable_windows"],
            },
            {
                "order": 5,
                "name": "acceptance_gate",
                "function": "evaluate_acceptance",
                "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                "checks": [
                    "robustness_improved vs phase9_8",
                    "overfitting_risk_decreased",
                    "mean_expectancy_positive",
                    "profitable_windows_ge_4",
                ],
            },
            {
                "order": 6,
                "name": "candidate_rejection",
                "mechanism": "Lower composite_score; skipped windows; experiment errors",
                "no_explicit_rejection_rules_for_probability": True,
            },
            {
                "order": 7,
                "name": "freeze_artifacts",
                "function": "freeze_phase9_9_artifacts",
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "note": "Retrain on first 85% RANGE slice; no probability audit before save",
            },
        ],
        "probability_metrics_in_selection": "NONE — see selection_criteria_audit.json",
        "production_modified": False,
    }


def audit_selection_criteria() -> dict[str, Any]:
    searched_terms = [
        "max probability", "buy_zone", "buy coverage", "sell coverage",
        "probability distribution", "calibration", "brier", "ece", "log_loss",
        "log loss", "pr_auc", "average_precision",
    ]
    code_paths_searched = [
        "tradingbot/ml/research/robustness_optimizer/",
        "tradingbot/ml/research/walk_forward/",
        "tradingbot/ml/paper_trading/model_registry.py",
    ]
    absent_in_selection = {
        "max_probability": True,
        "buy_zone_coverage": True,
        "sell_zone_coverage": True,
        "probability_histogram": True,
        "calibration_score": True,
        "brier_score": True,
        "ece": True,
        "log_loss_as_selection_metric": True,
        "pr_auc": True,
    }
    present_but_not_selection_gates = {
        "roc_auc": {
            "used_for": "train_val_auc_gap overfitting penalty only",
            "file": "candidate_selector.py overfitting_penalty",
            "used_as_ranking_threshold": False,
        },
        "precision_recall_f1": {
            "used_for": "per-window ML metrics logged in validate_window_candidate",
            "used_in_composite_score": False,
        },
        "threshold_strategy_0.55_0.45": {
            "used_for": "trade simulation PF/win_rate on validation",
            "validates_model_probability_spread": False,
            "note": "SELL-only probability mass can yield PF>1 without any BUY zone coverage",
        },
    }
    return {
        "phase": "22W",
        "searched_terms": searched_terms,
        "code_paths": code_paths_searched,
        "probability_quality_gates_absent": absent_in_selection,
        "related_metrics_present": present_but_not_selection_gates,
        "proof": (
            "rg search over robustness_optimizer and walk_forward returns zero matches for "
            "buy_zone, brier, calibration, ece, max_prob. composite_score uses only "
            "robustness_score, mean_profit_factor, expectancy_consistency, overfitting_penalty."
        ),
    }


def load_candidate_ranking(base_dir: str | Path | None = None) -> dict[str, Any]:
    from tradingbot.ml.data.paths import phase9_9_model_comparison_path

    path = phase9_9_model_comparison_path(base_dir)
    data = _load_json(path)
    ranked = data.get("ranked_candidates") or []
    best = data.get("best_candidate") or (ranked[0] if ranked else {})
    return {
        "source": str(path),
        "candidate_count": data.get("candidate_count", len(ranked)),
        "ranked_candidates": ranked,
        "winner": best,
        "baseline_phase9_8": data.get("baseline_phase9_8"),
    }


def analyze_candidates(ranked: list[dict[str, Any]], winner: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for i, c in enumerate(ranked):
        selected = c.get("experiment_id") == winner.get("experiment_id")
        rejected_reason = None
        if selected:
            status = "SELECTED_WINNER"
        elif c.get("skipped"):
            status = "REJECTED_SKIPPED"
            rejected_reason = c.get("reason", "skipped")
        else:
            status = "REJECTED_LOWER_RANK"
            if float(c.get("mean_profit_factor", 0)) > float(winner.get("mean_profit_factor", 0)):
                rejected_reason = "lower_composite_despite_higher_pf"
            elif float(c.get("robustness_score", 0)) < float(winner.get("robustness_score", 0)):
                rejected_reason = "lower_robustness_score"
            else:
                rejected_reason = "lower_composite_score"

        rows.append({
            "rank": i + 1,
            "experiment_id": c.get("experiment_id"),
            "candidate_id": c.get("candidate_id"),
            "model_name": c.get("model_name"),
            "feature_subset": c.get("feature_subset"),
            "composite_score": c.get("composite_score"),
            "robustness_score": c.get("robustness_score"),
            "mean_profit_factor": c.get("mean_profit_factor"),
            "mean_expectancy": c.get("mean_expectancy"),
            "mean_auc_gap": c.get("mean_auc_gap"),
            "profitable_windows": c.get("profitable_windows"),
            "overfitting_risk": c.get("overfitting_risk"),
            "status": status,
            "rejected_reason": rejected_reason,
            "probability_range": "NOT_STORED_IN_ARTIFACTS",
            "max_probability": "NOT_STORED_IN_ARTIFACTS",
            "buy_pct": "NOT_STORED_IN_ARTIFACTS",
            "sell_pct": "NOT_STORED_IN_ARTIFACTS",
            "win_rate": "NOT_STORED_IN_RANKING_JSON",
            "trades": "NOT_STORED_IN_RANKING_JSON",
        })

    higher_pf_lost = [
        r for r in rows
        if r["status"] == "REJECTED_LOWER_RANK"
        and r["rejected_reason"] == "lower_composite_despite_higher_pf"
    ]

    return {
        "candidates": rows,
        "winner_selected_by": {
            "primary": "highest composite_score",
            "composite_formula": "0.40*robustness + 0.25*PF_norm + 0.20*consistency + 0.15*(1-overfitting_penalty)",
            "proof_file": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
        },
        "higher_pf_rejected_count": len(higher_pf_lost),
        "higher_pf_rejected_examples": higher_pf_lost[:5],
        "buy_capable_candidate_evidence": {
            "found_in_artifacts": False,
            "note": (
                "phase9_9_model_comparison.json stores no per-candidate probability range or BUY %. "
                "Only frozen winner analyzed in Phase 22U: buy_zone=0%, max_p=0.434."
            ),
        },
    }


def first_engineering_mistake() -> dict[str, Any]:
    return {
        "phase": "22W",
        "verdict": PRIMARY_VERDICT,
        "question": "What is the FIRST engineering mistake that caused degenerated phase9_9?",
        "answer": PRIMARY_VERDICT,
        "chronology": [
            {
                "stage": "Feature subset stable_top3 includes structure_distance",
                "category": "FEATURES",
                "earlier": True,
                "note": "structure_distance train_importance=0.0 but stability_score=1.0 in feature_stability_report",
            },
            {
                "stage": "Phase 9.9 ranks candidates by PF/robustness composite without probability quality gate",
                "category": "MODEL_SELECTION_CRITERIA",
                "earlier": False,
                "note": "Direct decision that froze a model with 0% BUY zone (Phase 22U)",
            },
        ],
        "why_this_survives_as_primary": (
            "Walk-forward selection optimizes trade-simulation PF and robustness while never recording or "
            "rejecting models with zero BUY-zone coverage. The frozen winner (logistic_strong_reg__stable_top3) "
            "achieved PF≈1.31 with 99.9% sell-zone probabilities (22U). SELL-only models pass selection. "
            "This is the earliest decision that explicitly permitted deployment of a degenerated classifier."
        ),
        "rejected_alternatives": {
            "DATASET": "Labels balanced (36% positive, 22V); not corrupted",
            "LABELS": "Not imbalanced; ruled out in 22V",
            "MODEL": "Logistic choice is secondary; selection never tested probability spread",
            "FEATURES": "Contributing factor but selection could have blocked zero-BUY artifact",
            "TRAINING_PIPELINE": "85% slice is secondary; same criterion gap at freeze",
        },
    }


def impact_estimate() -> dict[str, Any]:
    return {
        "phase": "22W",
        "if_only_first_mistake_corrected": PRIMARY_VERDICT,
        "correction": "Add probability quality gate to rank/accept/freeze (e.g. require max_p>=0.55 or buy_zone>0)",
        "expected_buy_coverage": {
            "estimate": "Current winner would be rejected (22U: buy_zone=0%, max_p=0.434)",
            "evidence": "phase22u/training_probability_distribution.json",
        },
        "expected_probability_spread": {
            "estimate": "Unknown for alternate historical candidates — not stored in phase9_9 artifacts",
            "evidence": "candidate_probability_analysis.json",
        },
        "expected_pf_direction": {
            "estimate": "Winner ranked #1 partly due to PF=1.3087; lgbm_conservative__stable_4 had PF=1.3241 but lost on robustness composite",
            "evidence": "phase9_9_model_comparison.json ranks 1 vs 5",
        },
        "expected_trade_frequency": {
            "estimate": "Walk-forward trade sim uses fixed 0.55/0.45; SELL-only models can still produce trades and positive PF",
            "evidence": "model_validator.py _simulate_trades + 22U sell_zone 99.9%",
        },
        "repository_limitation": "No historical per-candidate probability artifacts; cannot prove any grid candidate had BUY coverage",
    }


def run_verification(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    ranking = load_candidate_ranking(base_dir)
    winner = ranking.get("winner") or {}
    candidate_analysis = analyze_candidates(ranking.get("ranked_candidates") or [], winner)

    return {
        "model_selection_pipeline": build_selection_pipeline_map(),
        "selection_criteria_audit": audit_selection_criteria(),
        "candidate_ranking": ranking,
        "candidate_probability_analysis": candidate_analysis,
        "first_engineering_mistake": first_engineering_mistake(),
        "impact_estimate": impact_estimate(),
        "verdict": PRIMARY_VERDICT,
    }
