"""Phase 9.3 — feature importance analysis (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.inspection import permutation_importance

from tradingbot.ml.data.paths import feature_importance_report_path
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.model_factory import DEFAULT_SEED, create_training_model
from tradingbot.ml.research.research_utils import ResearchContext, scaled_split_arrays

LOW_IMPORTANCE_THRESHOLD = 0.001
DEAD_VARIANCE_EPS = 1e-12
TREE_MODELS = ("random_forest", "xgboost", "lightgbm")


def _tree_importances(model_name: str, estimator: Any, feature_order: list[str]) -> dict[str, float]:
    if model_name == "random_forest":
        scores = getattr(estimator, "feature_importances_", None)
    elif model_name in ("xgboost", "lightgbm"):
        scores = getattr(estimator, "feature_importances_", None)
    else:
        return {}
    if scores is None:
        return {}
    return {feature_order[i]: float(scores[i]) for i in range(len(feature_order))}


def _rank_features(scores: dict[str, float]) -> list[dict[str, Any]]:
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [
        {"feature": name, "importance_score": round(score, 6), "rank": idx + 1}
        for idx, (name, score) in enumerate(ranked)
    ]


def _model_agreement(model_rankings: dict[str, list[str]], top_n: int = 15) -> dict[str, float]:
    """Fraction of models that rank each feature in top-N."""
    if not model_rankings:
        return {}
    features = set()
    for ranks in model_rankings.values():
        features.update(ranks[:top_n])
    agreement: dict[str, float] = {}
    n_models = len(model_rankings)
    for feat in features:
        count = sum(1 for ranks in model_rankings.values() if feat in ranks[:top_n])
        agreement[feat] = round(count / n_models, 4)
    return agreement


def _detect_feature_issues(
    X_train: np.ndarray,
    feature_order: list[str],
    combined_scores: dict[str, float],
) -> dict[str, list[str]]:
    dead: list[str] = []
    zero_var: list[str] = []
    low_contrib: list[str] = []

    for i, name in enumerate(feature_order):
        col = X_train[:, i]
        if np.nanstd(col) <= DEAD_VARIANCE_EPS:
            zero_var.append(name)
            dead.append(name)
        elif combined_scores.get(name, 0.0) < LOW_IMPORTANCE_THRESHOLD:
            low_contrib.append(name)

    return {
        "dead_features": dead,
        "zero_variance_features": zero_var,
        "low_contribution_features": low_contrib,
    }


def run_feature_importance_analysis(
    ctx: ResearchContext,
    *,
    seed: int = DEFAULT_SEED,
    permutation_n_repeats: int = 5,
) -> dict[str, Any]:
    """Analyze feature contribution using tree models and permutation importance."""
    arrays = scaled_split_arrays(ctx)
    X_train, y_train = arrays["train"]
    X_val, y_val = arrays["validation"]
    feature_order = list(ctx.pipeline.feature_order)

    model_importances: dict[str, dict[str, float]] = {}
    model_rankings: dict[str, list[str]] = {}

    for model_name in TREE_MODELS:
        wrapper = create_training_model(model_name, seed=seed)
        wrapper.fit(X_train, y_train, eval_set=(X_val, y_val))
        est = wrapper._estimator()
        imp = _tree_importances(model_name, est, feature_order)
        model_importances[model_name] = imp
        model_rankings[model_name] = [r["feature"] for r in _rank_features(imp)]

    perm_model = create_training_model("random_forest", seed=seed)
    perm_model.fit(X_train, y_train)
    perm_result = permutation_importance(
        perm_model._estimator(),
        X_val,
        y_val,
        n_repeats=permutation_n_repeats,
        random_state=seed,
        n_jobs=1,
    )
    perm_scores = {
        feature_order[i]: float(perm_result.importances_mean[i]) for i in range(len(feature_order))
    }
    model_importances["permutation"] = perm_scores
    model_rankings["permutation"] = [r["feature"] for r in _rank_features(perm_scores)]

    agreement = _model_agreement(model_rankings)

    combined: dict[str, float] = {}
    for name in feature_order:
        vals = [model_importances[m].get(name, 0.0) for m in model_importances]
        combined[name] = float(np.mean(vals)) if vals else 0.0

    ranked_combined = _rank_features(combined)
    for entry in ranked_combined:
        entry["model_agreement_score"] = agreement.get(entry["feature"], 0.0)

    issues = _detect_feature_issues(X_train, feature_order, combined)

    return {
        "phase": "9.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": ctx.symbol,
        "timeframe": ctx.timeframe,
        "feature_count": len(feature_order),
        "models_analyzed": list(TREE_MODELS) + ["permutation"],
        "rankings": ranked_combined,
        "per_model": {
            name: _rank_features(scores) for name, scores in model_importances.items()
        },
        "model_agreement": agreement,
        "detection": issues,
        "registry_features": feature_names(),
    }


def save_feature_importance_report(
    ctx: ResearchContext,
    base_dir: str | Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> Path:
    report = run_feature_importance_analysis(ctx, seed=seed)
    path = feature_importance_report_path(base_dir or ctx.base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
