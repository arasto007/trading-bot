"""Phase 10 — standardized ML shadow signal."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tradingbot.ml.shadow.ml_adapter import MLPrediction


@dataclass
class ShadowSignal:
    timestamp: str
    symbol: str
    direction: str
    probability: float
    confidence: float
    model_version: str
    features_hash: str
    timeframe: str = "M5"

    @classmethod
    def from_prediction(
        cls,
        prediction: MLPrediction,
        *,
        symbol: str,
        timeframe: str,
        model_version: str,
    ) -> "ShadowSignal":
        return cls(
            timestamp=prediction.timestamp,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            direction=prediction.direction,
            probability=prediction.probability,
            confidence=prediction.confidence,
            model_version=model_version,
            features_hash=prediction.features_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_trade(self) -> bool:
        return self.direction in ("BUY", "SELL")
