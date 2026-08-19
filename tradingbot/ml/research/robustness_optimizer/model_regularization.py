"""Phase 9.9 — regularized model candidate configurations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelCandidateConfig:
    candidate_id: str
    model_name: str
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "model_name": self.model_name,
            "hyperparameters": self.hyperparameters,
            "description": self.description,
        }


def build_regularized_candidates(
    baseline_hyperparameters: dict[str, Any] | None = None,
) -> list[ModelCandidateConfig]:
    """Conservative model grid aimed at reducing Phase 9.8 overfitting."""
    baseline = dict(baseline_hyperparameters or {})
    candidates: list[ModelCandidateConfig] = [
        ModelCandidateConfig(
            candidate_id="xgb_baseline_phase96",
            model_name="xgboost",
            hyperparameters=baseline or {
                "max_depth": 5,
                "learning_rate": 0.08,
                "n_estimators": 60,
                "subsample": 0.9,
                "colsample_bytree": 0.8,
            },
            description="Phase 9.6 baseline (deep XGBoost)",
        ),
        ModelCandidateConfig(
            candidate_id="xgb_shallow_d2",
            model_name="xgboost",
            hyperparameters={
                "max_depth": 2,
                "learning_rate": 0.05,
                "n_estimators": 40,
                "subsample": 0.85,
                "colsample_bytree": 0.8,
                "reg_alpha": 0.5,
                "reg_lambda": 1.0,
            },
            description="Shallow XGBoost depth=2",
        ),
        ModelCandidateConfig(
            candidate_id="xgb_regularized_d3",
            model_name="xgboost",
            hyperparameters={
                "max_depth": 3,
                "learning_rate": 0.05,
                "n_estimators": 50,
                "subsample": 0.8,
                "colsample_bytree": 0.7,
                "reg_alpha": 1.0,
                "reg_lambda": 2.0,
                "min_child_weight": 5,
            },
            description="Regularized XGBoost depth=3",
        ),
        ModelCandidateConfig(
            candidate_id="lgbm_conservative",
            model_name="lightgbm",
            hyperparameters={
                "max_depth": 3,
                "num_leaves": 8,
                "learning_rate": 0.05,
                "n_estimators": 50,
                "min_child_samples": 50,
                "subsample": 0.8,
                "colsample_bytree": 0.7,
                "reg_alpha": 0.5,
                "reg_lambda": 1.0,
            },
            description="Conservative LightGBM",
        ),
        ModelCandidateConfig(
            candidate_id="logistic_c1",
            model_name="logistic",
            hyperparameters={"C": 1.0},
            description="Logistic regression C=1.0",
        ),
        ModelCandidateConfig(
            candidate_id="logistic_strong_reg",
            model_name="logistic",
            hyperparameters={"C": 0.1},
            description="Strong L2 logistic C=0.1",
        ),
        ModelCandidateConfig(
            candidate_id="random_forest_shallow",
            model_name="random_forest",
            hyperparameters={"max_depth": 4, "n_estimators": 60, "min_samples_leaf": 20},
            description="Shallow random forest",
        ),
    ]
    return candidates


def apply_logistic_c(model_name: str, hyperparameters: dict[str, Any]) -> dict[str, Any]:
    """Pass-through; logistic C applied in create_regularized_model."""
    return dict(hyperparameters)


def create_regularized_model(
    candidate: ModelCandidateConfig,
    seed: int,
):
    """Build research model with full regularization hyperparameters (Phase 9.9 isolated)."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    from tradingbot.ml.training.model_factory import _SklearnWrapper

    name = candidate.model_name.lower()
    params = candidate.hyperparameters

    if name == "logistic":
        est = LogisticRegression(
            C=float(params.get("C", 1.0)),
            max_iter=500,
            random_state=seed,
            solver="lbfgs",
            n_jobs=1,
        )
        return _SklearnWrapper("logistic", est)

    if name == "random_forest":
        est = RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 60)),
            max_depth=int(params.get("max_depth", 4)),
            min_samples_leaf=int(params.get("min_samples_leaf", 1)),
            random_state=seed,
            n_jobs=1,
        )
        return _SklearnWrapper("random_forest", est)

    if name == "xgboost":
        import xgboost as xgb

        kwargs: dict[str, Any] = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": seed,
            "n_jobs": 1,
            "tree_method": "hist",
            "device": "cpu",
            "max_depth": int(params.get("max_depth", 3)),
            "learning_rate": float(params.get("learning_rate", 0.05)),
            "n_estimators": int(params.get("n_estimators", 50)),
            "subsample": float(params.get("subsample", 0.85)),
            "colsample_bytree": float(params.get("colsample_bytree", 0.8)),
        }
        if "reg_alpha" in params:
            kwargs["reg_alpha"] = float(params["reg_alpha"])
        if "reg_lambda" in params:
            kwargs["reg_lambda"] = float(params["reg_lambda"])
        if "min_child_weight" in params:
            kwargs["min_child_weight"] = float(params["min_child_weight"])
        return _SklearnWrapper("xgboost", xgb.XGBClassifier(**kwargs))

    if name == "lightgbm":
        import lightgbm as lgb

        est = lgb.LGBMClassifier(
            objective="binary",
            random_state=seed,
            n_jobs=1,
            verbosity=-1,
            learning_rate=float(params.get("learning_rate", 0.05)),
            max_depth=int(params.get("max_depth", 3)),
            n_estimators=int(params.get("n_estimators", 50)),
            num_leaves=int(params.get("num_leaves", 15)),
            min_child_samples=int(params.get("min_child_samples", 20)),
            subsample=float(params.get("subsample", 0.85)),
            colsample_bytree=float(params.get("colsample_bytree", 0.8)),
            reg_alpha=float(params.get("reg_alpha", 0.0)),
            reg_lambda=float(params.get("reg_lambda", 0.0)),
        )
        return _SklearnWrapper("lightgbm", est)

    from tradingbot.ml.research.retrain_optimizer import create_research_model

    return create_research_model(name, seed, params)
