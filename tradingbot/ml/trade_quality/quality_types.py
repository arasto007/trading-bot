"""Phase 14.3 — trade quality typed structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.confidence_engine.validator import CalibratedDecision
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.risk_intelligence.risk_types import RiskRecommendation


@dataclass
class TradeQualityContext:
    """Inputs for trade quality evaluation."""

    market: MarketContext
    calibrated: CalibratedDecision
    risk: RiskRecommendation
    engine: str | None
    regime: str
    action: str
    confidence: float
    risk_percent: float
    atr_percentile: float
    spread_pips: float
    spread_class: str
    session: str
    rr_ratio: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.market.symbol,
            "timeframe": self.market.timeframe,
            "engine": self.engine,
            "regime": self.regime,
            "action": self.action,
            "confidence": round(self.confidence, 6),
            "risk_percent": round(self.risk_percent, 4),
            "atr_percentile": round(self.atr_percentile, 4),
            "spread_pips": round(self.spread_pips, 4),
            "spread_class": self.spread_class,
            "session": self.session,
            "rr_ratio": round(self.rr_ratio, 4),
        }


@dataclass
class QualityScore:
    """Trade quality evaluation output."""

    allowed: bool
    score: float
    grade: str
    components: dict[str, float]
    reason: str
    trace: list[str] = field(default_factory=list)
    blocked_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "score": round(self.score, 4),
            "grade": self.grade,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "reason": self.reason,
            "trace": self.trace,
            "blocked_by": self.blocked_by,
        }
