"""Phase 17B — in-memory research RF model (NOT production bundle)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ResearchRfModel:
    """Offline research artifact — never written to trend_rf_bundle."""

    model: Any
    scaler: Any
    feature_order: list[str]
    seed: int = 42
    train_rows: int = 0
    phase: str = "17B"
    metadata: dict[str, Any] = field(default_factory=dict)

    def transform(self, row: pd.Series | dict[str, float]) -> np.ndarray:
        if isinstance(row, dict):
            frame = pd.DataFrame([{k: row[k] for k in self.feature_order}])
        else:
            frame = pd.DataFrame([{k: float(row.get(k, 0.0)) for k in self.feature_order}])
        return self.scaler.transform(frame.values)

    def predict_proba(self, row: pd.Series | dict[str, float]) -> float:
        X = self.transform(row)
        proba = self.model.predict_proba(X)[0]
        return float(proba[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "feature_order": self.feature_order,
            "train_rows": self.train_rows,
            "seed": self.seed,
            "metadata": self.metadata,
            "production_bundle": False,
            "frozen": False,
        }
