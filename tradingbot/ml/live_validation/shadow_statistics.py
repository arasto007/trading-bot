"""Phase 15D — shadow agreement / disagreement statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.live_validation.decision_compare import DecisionComparer
from tradingbot.ml.live_validation.risk_compare import RiskComparer
from tradingbot.ml.live_validation.shadow_trade import ShadowTrade


@dataclass
class ShadowStatistics:
    decision_comparer: DecisionComparer = field(default_factory=DecisionComparer)
    risk_comparer: RiskComparer = field(default_factory=RiskComparer)
    shadow_trades: list[ShadowTrade] = field(default_factory=list)
    bars_processed: int = 0
    ml_signals: int = 0
    legacy_signals: int = 0
    orders_blocked: int = 0

    def add_trade(self, trade: ShadowTrade) -> None:
        self.shadow_trades.append(trade)

    def build_report(self) -> dict[str, Any]:
        decision = self.decision_comparer.summary()
        risk = self.risk_comparer.summary()
        return {
            "bars_processed": self.bars_processed,
            "ml_signals": self.ml_signals,
            "legacy_signals": self.legacy_signals,
            "shadow_trades": len(self.shadow_trades),
            "orders_blocked": self.orders_blocked,
            "agreement": decision.get("agreement", 0),
            "disagreement": decision.get("disagreement", 0),
            "agreement_rate": decision.get("agreement_rate", 0.0),
            "direction_match_rate": decision.get("direction_match_rate", 0.0),
            "different_direction": decision.get("different_direction", 0),
            "mean_confidence_diff": decision.get("mean_confidence_diff", 0.0),
            "mean_risk_diff": decision.get("mean_risk_diff", 0.0),
            "mean_quality_diff": decision.get("mean_quality_diff", 0.0),
            "decision": decision,
            "risk": risk,
        }
