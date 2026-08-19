"""Base model interface for offline ML training (Phase 4.0)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class BaseModel(ABC):
    """Common interface for all baseline classifiers."""

    name: str = "base"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = dict(params or {})
        self.feature_names_: list[str] = []
        self._fitted = False

    @abstractmethod
    def fit(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray,
        *,
        sample_weight: np.ndarray | None = None,
        eval_set: tuple[Any, Any] | None = None,
    ) -> "BaseModel":
        ...

    @abstractmethod
    def predict(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        ...

    @abstractmethod
    def predict_proba(self, X: pd.DataFrame | np.ndarray) -> np.ndarray:
        ...

    @abstractmethod
    def save(self, directory: str | Path) -> Path:
        ...

    @classmethod
    @abstractmethod
    def load(cls, directory: str | Path) -> "BaseModel":
        ...

    def feature_importances(self) -> list[dict[str, float]]:
        """Return feature importance if supported."""
        return []

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def _validate_fitted(self) -> None:
        if not self._fitted:
            raise RuntimeError(f"{self.name} model is not fitted")

    def _as_frame(self, X: pd.DataFrame | np.ndarray) -> pd.DataFrame:
        if isinstance(X, pd.DataFrame):
            return X[self.feature_names_] if self.feature_names_ else X
        if self.feature_names_:
            return pd.DataFrame(X, columns=self.feature_names_)
        return pd.DataFrame(X)
