"""Baseline model factory for Phase 8.6 training (CPU-only, deterministic)."""

from __future__ import annotations

import pickle
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

DEFAULT_SEED = 42
SUPPORTED_MODELS = ("logistic", "random_forest", "xgboost", "lightgbm", "all")


class TrainingModel(ABC):
    """Minimal model interface for the production training pipeline."""

    name: str

    @abstractmethod
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        eval_set: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> TrainingModel:
        ...

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        ...

    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        ...

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump({"name": self.name, "model": self._estimator()}, fh)
        return path

    @classmethod
    def load(cls, path: str | Path) -> TrainingModel:
        with Path(path).open("rb") as fh:
            payload = pickle.load(fh)
        name = payload["name"]
        model = create_training_model(name)
        model._set_estimator(payload["model"])
        return model

    @abstractmethod
    def _estimator(self) -> Any:
        ...

    @abstractmethod
    def _set_estimator(self, estimator: Any) -> None:
        ...


class _SklearnWrapper(TrainingModel):
    def __init__(self, name: str, estimator: Any) -> None:
        self.name = name
        self._model = estimator

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        eval_set: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> _SklearnWrapper:
        self._model.fit(X, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.predict(X)).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.predict_proba(X))

    def _estimator(self) -> Any:
        return self._model

    def _set_estimator(self, estimator: Any) -> None:
        self._model = estimator


class _XGBoostWrapper(TrainingModel):
    def __init__(self, seed: int) -> None:
        self.name = "xgboost"
        self._seed = seed
        self._model = None

    def _build(self) -> Any:
        import xgboost as xgb

        return xgb.XGBClassifier(
            n_estimators=80,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=self._seed,
            n_jobs=1,
            tree_method="hist",
            device="cpu",
        )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        eval_set: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> _XGBoostWrapper:
        if self._model is None:
            self._model = self._build()
        if eval_set is not None:
            self._model.fit(X, y, eval_set=[eval_set], verbose=False)
        else:
            self._model.fit(X, y, verbose=False)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.predict(X)).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.predict_proba(X))

    def _estimator(self) -> Any:
        return self._model

    def _set_estimator(self, estimator: Any) -> None:
        self._model = estimator


class _LightGBMWrapper(TrainingModel):
    def __init__(self, seed: int) -> None:
        self.name = "lightgbm"
        self._seed = seed
        self._model = None

    def _build(self) -> Any:
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=80,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary",
            random_state=self._seed,
            n_jobs=1,
            verbosity=-1,
        )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        eval_set: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> _LightGBMWrapper:
        if self._model is None:
            self._model = self._build()
        if eval_set is not None:
            self._model.fit(
                X,
                y,
                eval_set=[eval_set],
                eval_metric="binary_logloss",
            )
        else:
            self._model.fit(X, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.predict(X)).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self._model.predict_proba(X))

    def _estimator(self) -> Any:
        return self._model

    def _set_estimator(self, estimator: Any) -> None:
        self._model = estimator


def create_training_model(name: str, seed: int = DEFAULT_SEED) -> TrainingModel:
    """Instantiate a baseline training model by name."""
    key = name.lower().strip()
    if key == "logistic":
        est = LogisticRegression(
            max_iter=500,
            random_state=seed,
            solver="lbfgs",
            n_jobs=1,
        )
        return _SklearnWrapper("logistic", est)
    if key in ("random_forest", "rf"):
        est = RandomForestClassifier(
            n_estimators=80,
            max_depth=6,
            random_state=seed,
            n_jobs=1,
        )
        return _SklearnWrapper("random_forest", est)
    if key == "xgboost":
        return _XGBoostWrapper(seed)
    if key == "lightgbm":
        return _LightGBMWrapper(seed)
    raise ValueError(f"Unsupported model: {name!r}. Choose from {SUPPORTED_MODELS}")


def resolve_model_list(model: str) -> list[str]:
    """Expand CLI model argument into concrete model names."""
    key = model.lower().strip()
    if key == "all":
        models = ["logistic", "random_forest"]
        try:
            import xgboost  # noqa: F401

            models.append("xgboost")
        except ImportError:
            pass
        try:
            import lightgbm  # noqa: F401

            if "xgboost" not in models:
                models.append("lightgbm")
        except ImportError:
            pass
        return models
    if key == "xgboost":
        import xgboost  # noqa: F401
    if key == "lightgbm":
        import lightgbm  # noqa: F401
    return [key]
