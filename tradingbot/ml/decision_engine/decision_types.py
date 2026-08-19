"""Phase 14.1 — typed decision structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Action = Literal["BUY", "SELL", "HOLD"]
Regime = Literal["RANGE", "TREND", "HIGH_VOLATILITY", "NO_TRADE"]


@dataclass(frozen=True)
class EngineSignal:
    """Output from a single strategy engine."""

    signal: Action
    confidence: float
    model: str
    probability: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "confidence": round(self.confidence, 6),
            "model": self.model,
            "probability": round(self.probability, 6),
            "metadata": self.metadata,
        }


@dataclass
class MarketContext:
    """Market state and pre-evaluated engine outputs for one decision bar."""

    symbol: str
    timeframe: str
    features: dict[str, Any]
    regime: str
    regime_strength: float
    range_signal: EngineSignal
    trend_signal: EngineSignal
    volatility: float
    session: str
    timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "regime_strength": round(self.regime_strength, 6),
            "volatility": round(self.volatility, 6),
            "session": self.session,
            "timestamp": (self.timestamp or datetime.now(timezone.utc)).isoformat(),
            "range_signal": self.range_signal.to_dict(),
            "trend_signal": self.trend_signal.to_dict(),
        }


@dataclass
class FinalDecision:
    """Unified trading decision produced by the orchestrator."""

    action: Action
    engine: str | None
    confidence: float
    regime: str
    timestamp: datetime
    explanation: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    risk_hint: float = 0.0
    trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "selected_engine": self.engine,
            "regime": self.regime,
            "confidence": round(self.confidence, 6),
            "risk_hint": round(self.risk_hint, 6),
            "timestamp": self.timestamp.isoformat(),
            "reason": self.explanation,
            "trace": self.trace,
            "metadata": self.metadata,
        }
