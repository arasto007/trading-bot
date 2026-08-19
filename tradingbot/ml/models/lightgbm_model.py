"""LightGBM classifier for offline baseline training."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.models.base import BaseModel

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None  # type: ignore


class LightGBMModel(BaseModel):
    name = "lightgbm"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        if lgb is None:
            raise ImportError("lightgbm is required — pip install lightgbm")
        self._model: lgb.LGBMClassifier | None = None

    def _build_estimator(self) -> "lgb.LGBMClassifier":
        assert lgb is not None
        return lgb.LGBMClassifier(
            num_leaves=int(self.params.get("num_leaves", 31)),
            learning_rate=float(self.params.get("learning_rate", 0.05)),
            n_estimators=int(self.params.get("n_estimators", 200)),
            max_depth=int(self.params.get("max_depth", -1)),
            class_weight="balanced" if self.params.get("use_class_weights", True) else None,
            objective="binary",
            random_state=int(self.params.get("random_state", 42)),
            n_jobs=int(self.params.get("n_jobs", -1)),
            verbose=-1,
        )

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
        *,
        sample_weight: np.ndarray | None = None,
        eval_set: tuple[Any, Any] | None = None,
    ) -> "LightGBMModel":
        frame = self._as_frame(X) if isinstance(X, np.ndarray) else X
        self.feature_names_ = list(frame.columns)
        y_arr = np.asarray(y).astype(int)
        self._model = self._build_estimator()

        fit_kwargs: dict[str, Any] = {}
        if eval_set is not None:
            X_eval, y_eval = eval_set
            if isinstance(X_eval, pd.DataFrame):
                X_eval = X_eval[self.feature_names_]
            fit_kwargs["eval_set"] = [(X_eval, np.asarray(y_eval).astype(int))]

        self._model.fit(frame, y_arr, sample_weight=sample_weight, **fit_kwargs)
        self._fitted = True
        return self

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        self._validate_fitted()
        assert self._model is not None
        return self._model.predict(self._as_frame(X))

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        self._validate_fitted()
        assert self._model is not None
        return self._model.predict_proba(self._as_frame(X))

    def feature_importances(self) -> list[dict[str, float]]:
        self._validate_fitted()
        assert self._model is not None
        scores = self._model.feature_importances_
        pairs = sorted(zip(self.feature_names_, scores), key=lambda x: -x[1])
        return [{"name": n, "importance": round(float(v), 6)} for n, v in pairs]

    def save(self, directory: str | Path) -> Path:
        self._validate_fitted()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "model.pkl"
        with path.open("wb") as f:
            pickle.dump(
                {
                    "model": self._model,
                    "feature_names": self.feature_names_,
                    "params": self.params,
                },
                f,
            )
        return path

    @classmethod
    def load(cls, directory: str | Path) -> "LightGBMModel":
        if lgb is None:
            raise ImportError("lightgbm is required")
        directory = Path(directory)
        with (directory / "model.pkl").open("rb") as f:
            payload = pickle.load(f)
        model = cls(params=payload.get("params", {}))
        model._model = payload["model"]
        model.feature_names_ = payload.get("feature_names", [])
        model._fitted = True
        return model
