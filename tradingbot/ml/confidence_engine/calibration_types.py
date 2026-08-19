"""Phase 14.2A — confidence calibration typed structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VolatilityState = Literal["LOW_VOL", "NORMAL", "HIGH_VOL", "EXTREME"]
ConfidenceBand = Literal["LOW", "MEDIUM", "HIGH", "ZERO"]
SessionName = Literal["ASIA", "LONDON", "NEW_YORK", "OFF_SESSION"]


@dataclass(frozen=True)
class RawConfidence:
    """Raw confidence context from Phase 14.1 decision output."""

    raw_value: float
    engine: str | None
    regime: str
    model_probability: float
    regime_strength: float
    market_quality: float
    session: str
    volatility: float
    volatility_state: VolatilityState = "NORMAL"
    engine_signal: str = "HOLD"

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_value": round(self.raw_value, 6),
            "engine": self.engine,
            "regime": self.regime,
            "model_probability": round(self.model_probability, 6),
            "regime_strength": round(self.regime_strength, 6),
            "market_quality": round(self.market_quality, 6),
            "session": self.session,
            "volatility": round(self.volatility, 6),
            "volatility_state": self.volatility_state,
            "engine_signal": self.engine_signal,
        }


@dataclass
class CalibratedConfidence:
    """Calibrated confidence with explainability."""

    calibrated_value: float
    adjustment_factor: float
    confidence_band: ConfidenceBand
    explanation: list[str]
    trace: list[str] = field(default_factory=list)
    adjustments: list[str] = field(default_factory=list)
    raw_value: float = 0.0
    engine: str | None = None
    regime: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibrated_value": round(self.calibrated_value, 6),
            "adjustment_factor": round(self.adjustment_factor, 6),
            "confidence_band": self.confidence_band,
            "explanation": self.explanation,
            "trace": self.trace,
            "adjustments": self.adjustments,
            "raw_value": round(self.raw_value, 6),
            "engine": self.engine,
            "regime": self.regime,
        }
