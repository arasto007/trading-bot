"""XGBoost classifier for offline baseline training."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.models.base import BaseModel

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover
    xgb = None  # type: ignore


class XGBoostModel(BaseModel):
    name = "xgboost"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        if xgb is None:
            raise ImportError("xgboost is required — pip install xgboost")
        self._model: xgb.XGBClassifier | None = None

    def _build_estimator(self, y: np.ndarray) -> "xgb.XGBClassifier":
        assert xgb is not None
        n_pos = int((y == 1).sum())
        n_neg = int((y == 0).sum())
        scale = n_neg / max(n_pos, 1) if self.params.get("use_class_weights", True) else 1.0
        return xgb.XGBClassifier(
            n_estimators=int(self.params.get("n_estimators", 200)),
            max_depth=int(self.params.get("max_depth", 6)),
            learning_rate=float(self.params.get("learning_rate", 0.05)),
            subsample=float(self.params.get("subsample", 0.8)),
            colsample_bytree=float(self.params.get("colsample_bytree", 0.8)),
            scale_pos_weight=float(self.params.get("scale_pos_weight", scale)),
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=int(self.params.get("random_state", 42)),
            n_jobs=int(self.params.get("n_jobs", -1)),
        )

    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
        *,
        sample_weight: np.ndarray | None = None,
        eval_set: tuple[Any, Any] | None = None,
    ) -> "XGBoostModel":
        frame = self._as_frame(X) if isinstance(X, np.ndarray) else X
        self.feature_names_ = list(frame.columns)
        y_arr = np.asarray(y).astype(int)
        self._model = self._build_estimator(y_arr)

        fit_kwargs: dict[str, Any] = {}
        if eval_set is not None:
            X_eval, y_eval = eval_set
            if isinstance(X_eval, pd.DataFrame):
                X_eval = X_eval[self.feature_names_]
            fit_kwargs["eval_set"] = [(X_eval, np.asarray(y_eval).astype(int))]
            fit_kwargs["verbose"] = False

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
        pairs = sorted(
            zip(self.feature_names_, scores),
            key=lambda x: -x[1],
        )
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
    def load(cls, directory: str | Path) -> "XGBoostModel":
        if xgb is None:
            raise ImportError("xgboost is required")
        directory = Path(directory)
        with (directory / "model.pkl").open("rb") as f:
            payload = pickle.load(f)
        model = cls(params=payload.get("params", {}))
        model._model = payload["model"]
        model.feature_names_ = payload.get("feature_names", [])
        model._fitted = True
        return model
