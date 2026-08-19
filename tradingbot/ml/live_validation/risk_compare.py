"""Phase 15D — risk gate comparison (read-only evaluate)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RiskComparisonRecord:
    timestamp: str
    legacy_would_trade: bool
    ml_would_trade: bool
    ml_risk_allowed: bool
    ml_risk_reason: str
    legacy_confidence: float
    ml_confidence: float
    ml_risk_percent: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "legacy_would_trade": self.legacy_would_trade,
            "ml_would_trade": self.ml_would_trade,
            "ml_risk_allowed": self.ml_risk_allowed,
            "ml_risk_reason": self.ml_risk_reason,
            "legacy_confidence": round(self.legacy_confidence, 6),
            "ml_confidence": round(self.ml_confidence, 6),
            "ml_risk_percent": round(self.ml_risk_percent, 6),
        }


@dataclass
class RiskComparer:
    records: list[RiskComparisonRecord] = field(default_factory=list)

    def compare(
        self,
        *,
        timestamp: str,
        legacy_signal: Any | None,
        ml_signal: Any | None,
        risk_decision: Any | None,
        ml_unified: Any | None = None,
    ) -> RiskComparisonRecord:
        leg_conf = float(getattr(legacy_signal, "confidence", 0.0)) if legacy_signal else 0.0
        ml_conf = float(ml_unified.confidence if ml_unified else getattr(ml_signal, "confidence", 0.0) if ml_signal else 0.0)
        ml_risk = float(ml_unified.risk if ml_unified else 0.0)
        allowed = bool(getattr(risk_decision, "allowed", False)) if risk_decision else False
        reason = str(getattr(risk_decision, "reason", "")) if risk_decision else ""

        rec = RiskComparisonRecord(
            timestamp=timestamp,
            legacy_would_trade=legacy_signal is not None,
            ml_would_trade=ml_signal is not None,
            ml_risk_allowed=allowed,
            ml_risk_reason=reason,
            legacy_confidence=leg_conf,
            ml_confidence=ml_conf,
            ml_risk_percent=ml_risk,
        )
        self.records.append(rec)
        return rec

    def summary(self) -> dict[str, Any]:
        n = len(self.records)
        if not n:
            return {"total": 0}
        return {
            "total": n,
            "ml_risk_allowed_count": sum(1 for r in self.records if r.ml_risk_allowed),
            "ml_would_trade_count": sum(1 for r in self.records if r.ml_would_trade),
            "legacy_would_trade_count": sum(1 for r in self.records if r.legacy_would_trade),
            "both_signals_count": sum(1 for r in self.records if r.legacy_would_trade and r.ml_would_trade),
        }
