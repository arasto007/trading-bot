"""Phase 9.3 — hyperparameter optimization (research only, validation-scored)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, PredefinedSplit

from tradingbot.ml.data.paths import model_optimization_report_path
from tradingbot.ml.training.model_factory import DEFAULT_SEED
from tradingbot.ml.research.research_utils import ResearchContext, scaled_split_arrays


def _build_xgb(seed: int) -> Any:
    import xgboost as xgb

    return xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=seed,
        n_jobs=1,
        tree_method="hist",
        device="cpu",
    )


def _build_lgbm(seed: int) -> Any:
    import lightgbm as lgb

    return lgb.LGBMClassifier(
        objective="binary",
        random_state=seed,
        n_jobs=1,
        verbosity=-1,
    )


XGB_PARAM_GRID: dict[str, list[Any]] = {
    "max_depth": [3, 4, 5],
    "learning_rate": [0.05, 0.08],
    "n_estimators": [60, 80],
    "subsample": [0.8, 0.9],
    "colsample_bytree": [0.8, 0.9],
}

LGBM_PARAM_GRID: dict[str, list[Any]] = {
    "num_leaves": [15, 31],
    "learning_rate": [0.05, 0.08],
    "n_estimators": [60, 80],
    "max_depth": [3, 4, 5],
}


def _optimize_model(
    model_name: str,
    estimator: Any,
    param_grid: dict[str, list[Any]],
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    seed: int,
) -> dict[str, Any]:
    """Fit on train only; score on validation via PredefinedSplit (no shuffle, no test)."""
    X_combined = np.vstack([X_train, X_val])
    y_combined = np.concatenate([y_train, y_val])
    test_fold = np.full(len(X_combined), -1, dtype=int)
    test_fold[len(X_train) :] = 0

    search = GridSearchCV(
        estimator,
        param_grid,
        cv=PredefinedSplit(test_fold),
        scoring="roc_auc",
        n_jobs=1,
        refit=False,
        error_score=0.0,
    )
    search.fit(X_combined, y_combined)

    best_params = search.best_params_
    best_est = estimator.set_params(**best_params)
    best_est.fit(X_train, y_train)
    val_proba = best_est.predict_proba(X_val)[:, 1]
    val_auc = float(roc_auc_score(y_val, val_proba)) if len(np.unique(y_val)) > 1 else 0.0

    return {
        "model": model_name,
        "best_params": best_params,
        "validation_roc_auc": round(val_auc, 4),
        "cv_best_score": round(float(search.best_score_), 4),
        "n_candidates": len(search.cv_results_["params"]),
    }


def run_model_optimization(
    ctx: ResearchContext,
    *,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Optimize XGBoost and LightGBM hyperparameters on train/validation only."""
    arrays = scaled_split_arrays(ctx)
    X_train, y_train = arrays["train"]
    X_val, y_val = arrays["validation"]

    results: list[dict[str, Any]] = []
    results.append(
        _optimize_model(
            "xgboost",
            _build_xgb(seed),
            XGB_PARAM_GRID,
            X_train,
            y_train,
            X_val,
            y_val,
            seed=seed,
        )
    )
    results.append(
        _optimize_model(
            "lightgbm",
            _build_lgbm(seed),
            LGBM_PARAM_GRID,
            X_train,
            y_train,
            X_val,
            y_val,
            seed=seed,
        )
    )

    best = max(results, key=lambda r: r["validation_roc_auc"])
    return {
        "phase": "9.3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": ctx.symbol,
        "timeframe": ctx.timeframe,
        "seed": seed,
        "method": "GridSearchCV",
        "validation_rules": {
            "chronological_split": True,
            "shuffle": False,
            "test_used_in_optimization": False,
        },
        "models": results,
        "best_model": best["model"],
        "best_validation_roc_auc": best["validation_roc_auc"],
    }


def save_model_optimization_report(
    ctx: ResearchContext,
    base_dir: str | Path | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> Path:
    report = run_model_optimization(ctx, seed=seed)
    path = model_optimization_report_path(base_dir or ctx.base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
