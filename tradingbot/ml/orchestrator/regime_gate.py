"""Regime gate — trend, range, high volatility, news."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.ml.memory.schema import regime_from_features
from tradingbot.ml.orchestrator.schema import OrchestratorSnapshot


@dataclass
class RegimeGateResult:
    regime: str = "unknown"
    allow_ml: bool = True
    favor_rule: bool = False
    reduce_frequency: bool = False
    force_wait: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class RegimeGate:
    """Apply regime-specific trading constraints."""

    def evaluate(self, snapshot: OrchestratorSnapshot) -> RegimeGateResult:
        feats = snapshot.features_snapshot or {}
        regime = snapshot.regime if snapshot.regime != "unknown" else regime_from_features(feats)
        result = RegimeGateResult(regime=regime)

        news = float(feats.get("news_event", feats.get("spread_spike", 0.0))) >= 0.5
        if news:
            result.force_wait = True
            result.regime = "news"
            result.reasons.append("News regime — WAIT mode")
            return result

        if regime == "trend":
            result.allow_ml = True
            result.reasons.append("Trend regime — ML allowed")
        elif regime == "range":
            result.favor_rule = True
            result.allow_ml = False
            result.reasons.append("Range regime — favor rule system")
        elif regime == "high_volatility":
            result.reduce_frequency = True
            result.reasons.append("High volatility — reduced trade frequency")
        elif regime == "low_volatility":
            result.reasons.append("Low volatility — normal gating")

        return result
