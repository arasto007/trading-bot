"""Phase 14.2B — frozen risk policy limits."""

from __future__ import annotations

from dataclasses import dataclass

BASE_RISK_PERCENT = 0.25
MAX_RISK_PERCENT = 0.50
MIN_CONFIDENCE_FOR_RISK = 0.55
BLOCK_ATR_PERCENTILE = 90.0
BLOCK_DRAWDOWN_PERCENT = 8.0


@dataclass(frozen=True)
class RiskPolicy:
    base_risk_percent: float = BASE_RISK_PERCENT
    max_risk_percent: float = MAX_RISK_PERCENT
    min_confidence: float = MIN_CONFIDENCE_FOR_RISK
    block_atr_percentile: float = BLOCK_ATR_PERCENTILE
    block_drawdown_percent: float = BLOCK_DRAWDOWN_PERCENT

    def clamp_risk(self, risk_percent: float) -> float:
        return max(0.0, min(float(risk_percent), self.max_risk_percent))


DEFAULT_RISK_POLICY = RiskPolicy()
