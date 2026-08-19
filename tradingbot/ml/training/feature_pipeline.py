"""Frozen feature order and train-only scaling for Phase 8.6."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import training_feature_order_path, training_scaler_path
from tradingbot.ml.features import feature_names


@dataclass
class FeaturePipeline:
    """Fit scaler on train split only; transform all splits with frozen column order."""

    feature_order: list[str]
    scaler: StandardScaler | None = None

    @classmethod
    def from_registry(cls) -> FeaturePipeline:
        return cls(feature_order=list(feature_names()))

    def fit(self, X_train: pd.DataFrame) -> FeaturePipeline:
        order = self._validate_columns(X_train)
        self.feature_order = order
        self.scaler = StandardScaler()
        self.scaler.fit(X_train.loc[:, order].astype(np.float64).values)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        if self.scaler is None:
            raise RuntimeError("FeaturePipeline must be fit before transform")
        order = self._validate_columns(X)
        if order != self.feature_order:
            raise ValueError("Feature column order mismatch during transform")
        return self.scaler.transform(X.loc[:, order].astype(np.float64).values)

    def fit_transform_train(
        self,
        X_train: pd.DataFrame,
        X_val: pd.DataFrame,
        X_test: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        self.fit(X_train)
        return self.transform(X_train), self.transform(X_val), self.transform(X_test)

    def save(self, version: str | int, base_dir: str | Path | None = None) -> tuple[Path, Path]:
        if self.scaler is None:
            raise RuntimeError("Cannot save unfitted FeaturePipeline")
        ver = str(version).lstrip("v")
        scaler_path = training_scaler_path(ver, base_dir)
        order_path = training_feature_order_path(ver, base_dir)
        scaler_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.scaler, scaler_path)
        order_path.write_text(
            json.dumps({"feature_order": self.feature_order}, indent=2),
            encoding="utf-8",
        )
        return scaler_path, order_path

    @classmethod
    def load(cls, version: str | int, base_dir: str | Path | None = None) -> FeaturePipeline:
        ver = str(version).lstrip("v")
        scaler = joblib.load(training_scaler_path(ver, base_dir))
        payload = json.loads(training_feature_order_path(ver, base_dir).read_text(encoding="utf-8"))
        order = payload.get("feature_order") or payload.get("features")
        if not order:
            raise ValueError(f"Invalid feature order file for version v{ver}")
        return cls(feature_order=list(order), scaler=scaler)

    def metadata(self) -> dict[str, Any]:
        return {
            "feature_count": len(self.feature_order),
            "feature_order": list(self.feature_order),
            "scaler": "StandardScaler",
        }

    def _validate_columns(self, X: pd.DataFrame) -> list[str]:
        if not self.feature_order:
            self.feature_order = list(feature_names())
        missing = [c for c in self.feature_order if c not in X.columns]
        if missing:
            raise ValueError(f"Missing feature columns: {missing[:5]}")
        empty = [c for c in self.feature_order if X[c].isna().all()]
        if empty:
            raise ValueError(f"Feature columns are entirely NaN: {empty[:5]}")
        return list(self.feature_order)
