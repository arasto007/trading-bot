"""Phase 17A — candidate architecture matrix (paper / estimate only)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17a.config import EVIDENCE, TOP5_FEATURES

# Architecture IDs A–L as specified.
ARCHITECTURES: list[dict[str, Any]] = [
    {
        "id": "A",
        "name": "Current Frozen RF",
        "model_family": "random_forest",
        "features": "current",
        "retrain": False,
        "ensemble": False,
        "description": "Production trend_rf_v40 frozen bundle (status quo).",
    },
    {
        "id": "B",
        "name": "Frozen RF + Top 5 features",
        "model_family": "random_forest",
        "features": "current_plus_top5",
        "retrain": False,
        "ensemble": False,
        "description": "Keep frozen weights; inject top-5 candidates without retrain (not viable — RF cannot consume unseen features).",
        "viable": False,
        "viability_note": "Frozen RF feature_order is fixed; new features require retrain.",
    },
    {
        "id": "C",
        "name": "New RF + Top 5 features",
        "model_family": "random_forest",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": False,
        "description": "Retrain RF on current + top-5 features; preserve sklearn RF interface.",
    },
    {
        "id": "D",
        "name": "Gradient Boosting + Current features",
        "model_family": "sklearn_gbm",
        "features": "current",
        "retrain": True,
        "ensemble": False,
        "description": "sklearn GradientBoostingClassifier on existing TREND_ML features.",
    },
    {
        "id": "E",
        "name": "Gradient Boosting + Top features",
        "model_family": "sklearn_gbm",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": False,
        "description": "sklearn GBM on current + top-5 features.",
    },
    {
        "id": "F",
        "name": "LightGBM + Current features",
        "model_family": "lightgbm",
        "features": "current",
        "retrain": True,
        "ensemble": False,
        "description": "LightGBM on existing features only.",
    },
    {
        "id": "G",
        "name": "LightGBM + Top features",
        "model_family": "lightgbm",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": False,
        "description": "LightGBM on current + top-5 features.",
    },
    {
        "id": "H",
        "name": "XGBoost + Current features",
        "model_family": "xgboost",
        "features": "current",
        "retrain": True,
        "ensemble": False,
        "description": "XGBoost on existing features only.",
    },
    {
        "id": "I",
        "name": "XGBoost + Top features",
        "model_family": "xgboost",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": False,
        "description": "XGBoost on current + top-5 features.",
    },
    {
        "id": "J",
        "name": "Stacked Ensemble (RF + GBM)",
        "model_family": "stack_rf_gbm",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": True,
        "description": "Stack frozen/new RF with sklearn GBM meta-learner.",
    },
    {
        "id": "K",
        "name": "Stacked Ensemble (RF + LightGBM)",
        "model_family": "stack_rf_lgbm",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": True,
        "description": "Stack RF with LightGBM meta-learner.",
    },
    {
        "id": "L",
        "name": "Stacked Ensemble (RF + XGBoost)",
        "model_family": "stack_rf_xgb",
        "features": "current_plus_top5",
        "retrain": True,
        "ensemble": True,
        "description": "Stack RF with XGBoost meta-learner.",
    },
]


def build_architecture_matrix() -> dict[str, Any]:
    """Paper-only architecture catalog with evidence anchors."""
    return {
        "phase": "17A",
        "evaluation_only": True,
        "production_modified": False,
        "top5_features": list(TOP5_FEATURES),
        "evidence_anchors": dict(EVIDENCE),
        "architectures": ARCHITECTURES,
        "count": len(ARCHITECTURES),
        "notes": [
            "Option B is not production-viable without retrain (frozen feature_order).",
            "Estimates use Phase 16D surrogate ceilings as upper bounds, not live guarantees.",
            "RANGE engine (phase9_9) remains isolated in all options.",
        ],
    }
