"""ML decision schema — shadow-mode trading suggestions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MLDecision:
    timestamp: str
    symbol: str
    timeframe: str
    model_name: str
    model_version: str
    prediction: int
    probability: float
    direction: str
    confidence: str
    threshold_used: float
    accepted: bool
    reason: str
    features_hash: str = ""
    dataset_version: str = ""
    explanation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MLDecision":
        return cls(
            timestamp=data.get("timestamp", ""),
            symbol=data.get("symbol", ""),
            timeframe=data.get("timeframe", ""),
            model_name=data.get("model_name", ""),
            model_version=data.get("model_version", ""),
            prediction=int(data.get("prediction", 0)),
            probability=float(data.get("probability", 0.0)),
            direction=data.get("direction", "NEUTRAL"),
            confidence=data.get("confidence", "LOW"),
            threshold_used=float(data.get("threshold_used", 0.5)),
            accepted=bool(data.get("accepted", False)),
            reason=data.get("reason", ""),
            features_hash=data.get("features_hash", ""),
            dataset_version=data.get("dataset_version", ""),
            explanation=data.get("explanation", {}),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def direction_label(raw_direction: int | float | None) -> str:
    if raw_direction is None:
        return "NEUTRAL"
    if raw_direction > 0:
        return "BUY"
    if raw_direction < 0:
        return "SELL"
    return "NEUTRAL"
