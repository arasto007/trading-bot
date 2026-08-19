"""ML adapter — wraps MLPredictor without modification."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision.predictor import MLPredictor
from tradingbot.ml.hybrid.schema import MLSignal


class MLAdapter:
    """Thin wrapper over Phase 5.0 MLPredictor."""

    def __init__(self, predictor: MLPredictor) -> None:
        self.predictor = predictor

    def predict(self, feature_row: dict[str, Any] | pd.Series) -> MLSignal:
        decision = self.predictor.predict_row(feature_row)
        return MLSignal(
            prediction=decision.prediction,
            probability=decision.probability,
            direction=decision.direction,
            confidence=decision.confidence,
            accepted=decision.accepted,
        )

    def predict_with_raw(self, feature_row: dict[str, Any] | pd.Series) -> tuple[MLSignal, Any]:
        decision = self.predictor.predict_row(feature_row)
        signal = MLSignal(
            prediction=decision.prediction,
            probability=decision.probability,
            direction=decision.direction,
            confidence=decision.confidence,
            accepted=decision.accepted,
        )
        return signal, decision
