"""Phase 13.4 — trend ML model factory (isolated from production models)."""

from __future__ import annotations

from typing import Any


def create_trend_ml_model(name: str, *, seed: int = 42) -> Any:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    if name == "logistic":
        return LogisticRegression(max_iter=500, random_state=seed)
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10
        )
    if name == "xgboost":
        try:
            from xgboost import XGBClassifier

            return XGBClassifier(
                n_estimators=120,
                max_depth=5,
                learning_rate=0.05,
                random_state=seed,
                eval_metric="logloss",
                verbosity=0,
            )
        except ImportError:
            return RandomForestClassifier(n_estimators=80, max_depth=5, random_state=seed)
    if name == "lightgbm":
        try:
            from lightgbm import LGBMClassifier

            return LGBMClassifier(
                n_estimators=120,
                max_depth=5,
                learning_rate=0.05,
                random_state=seed,
                verbose=-1,
            )
        except ImportError:
            return RandomForestClassifier(n_estimators=80, max_depth=5, random_state=seed)
    raise ValueError(f"Unknown trend ML model: {name}")


def available_trend_ml_candidates() -> list[str]:
    candidates = ["logistic", "random_forest"]
    try:
        import xgboost  # noqa: F401

        candidates.append("xgboost")
    except ImportError:
        pass
    try:
        import lightgbm  # noqa: F401

        candidates.append("lightgbm")
    except ImportError:
        pass
    return candidates
