"""Phase 14.1 — configurable decision policy."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.decision_engine.decision_types import Action

# Phase 13.10 validated production references (frozen — do not optimize here).
TREND_MODEL_ID = "trend_rf_v40"
TREND_ML_THRESHOLD = 0.40
RANGE_MODEL_ID = "phase9_9"
VOL_REGIME_ENGINE_ID = "vol_regime"
VOL_REGIME_RULE_CONFIDENCE = 0.60

DEFAULT_MIN_CONFIDENCE = 0.55


@dataclass(frozen=True)
class DecisionPolicy:
    """Gate decisions below minimum confidence."""

    min_confidence: float = DEFAULT_MIN_CONFIDENCE
    vol_regime_enabled: bool = True

    def apply(self, action: Action, confidence: float) -> Action:
        if action not in ("BUY", "SELL"):
            return "HOLD"
        if confidence < self.min_confidence:
            return "HOLD"
        return action

    def rejection_reason(self, confidence: float) -> str | None:
        if confidence < self.min_confidence:
            return f"confidence {confidence:.4f} below threshold {self.min_confidence:.4f}"
        return None


DEFAULT_POLICY = DecisionPolicy()
