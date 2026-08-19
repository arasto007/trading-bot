"""Logistic regression baseline model."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

from tradingbot.ml.models.base import BaseModel
from tradingbot.ml.models.dataset_loader import class_weights_from_labels


class LogisticModel(BaseModel):
    name = "logistic"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        lr_params = {
            "max_iter": int(self.params.get("max_iter", 2000)),
            "C": float(self.params.get("C", 1.0)),
            "solver": str(self.params.get("solver", "lbfgs")),
            "random_state": int(self.params.get("random_state", 42)),
        }
        self._pipeline = Pipeline(
            [
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(**lr_params)),
            ]
        )

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
        *,
        sample_weight: np.ndarray | None = None,
        eval_set: tuple[Any, Any] | None = None,
    ) -> "LogisticModel":
        frame = self._as_frame(X) if isinstance(X, np.ndarray) else X
        self.feature_names_ = list(frame.columns)
        y_arr = np.asarray(y).astype(int)

        if sample_weight is None and self.params.get("use_class_weights", True):
            weights = class_weights_from_labels(pd.Series(y_arr))
            sample_weight = np.array([weights[int(v)] for v in y_arr])

        self._pipeline.fit(frame, y_arr, clf__sample_weight=sample_weight)
        self._fitted = True
        return self

    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        self._validate_fitted()
        return self._pipeline.predict(self._as_frame(X))

    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        self._validate_fitted()
        return self._pipeline.predict_proba(self._as_frame(X))

    def save(self, directory: str | Path) -> Path:
        self._validate_fitted()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "model.pkl"
        with path.open("wb") as f:
            pickle.dump(
                {
                    "pipeline": self._pipeline,
                    "feature_names": self.feature_names_,
                    "params": self.params,
                },
                f,
            )
        return path

    @classmethod
    def load(cls, directory: str | Path) -> "LogisticModel":
        directory = Path(directory)
        path = directory / "model.pkl"
        with path.open("rb") as f:
            payload = pickle.load(f)
        model = cls(params=payload.get("params", {}))
        model._pipeline = payload["pipeline"]
        model.feature_names_ = payload.get("feature_names", [])
        model._fitted = True
        return model
