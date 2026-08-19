"""Phase 15I — range confidence recovery adapter."""

from __future__ import annotations

from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.phase15a.config import RANGE_ENGINE_ID
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id


class RangeAwareConfidenceEngine(ConfidenceEngine):
    """
    Recover engine confidence collapsed by regime_strength × market_quality.

    RANGE (phase9_9) and TREND (active trend engine) use directional model
    probability when the engine emits BUY/SELL — mirrors Phase 15I RANGE fix
    extended to TREND in Phase 22D.
    """

    def from_context(self, context: MarketContext, model_confidence: float) -> float:
        regime = str(context.regime).upper()
        engine_id = select_engine(regime)
        if engine_id is None:
            return super().from_context(context, model_confidence)

        active_trend = resolve_active_trend_engine_id()
        use_recovery = (
            (regime == "RANGE" and engine_id == RANGE_ENGINE_ID)
            or (regime == "TREND" and engine_id in (active_trend, "trend_rf_v40"))
        )
        if use_recovery:
            selected = select_signal(context, engine_id)
            if selected is not None and selected.signal in ("BUY", "SELL"):
                prob = float(selected.probability)
                directional = prob if selected.signal == "BUY" else 1.0 - prob
                return self.compute(
                    model_confidence=max(float(model_confidence), directional),
                    regime_strength=1.0,
                    market_quality=1.0,
                )
        return super().from_context(context, model_confidence)


class RangeRecoveryOrchestrator:
    """Thin wrapper — injects RangeAwareConfidenceEngine without modifying DecisionPolicy."""

    def __init__(self, inner: DecisionOrchestrator | None = None, **kwargs) -> None:
        self.inner = inner or DecisionOrchestrator(
            confidence_engine=RangeAwareConfidenceEngine(),
            **kwargs,
        )
        if not isinstance(self.inner.confidence_engine, RangeAwareConfidenceEngine):
            self.inner = DecisionOrchestrator(
                policy=self.inner.policy,
                confidence_engine=RangeAwareConfidenceEngine(),
                persist_traces=self.inner.persist_traces,
                base_dir=self.inner.base_dir,
            )
        self.policy = self.inner.policy
        self.confidence_engine = self.inner.confidence_engine
        self.persist_traces = self.inner.persist_traces
        self.base_dir = self.inner.base_dir

    def decide(self, market_context: MarketContext):
        return self.inner.decide(market_context)


def build_range_recovery_orchestrator(
    *,
    base_dir: str | None = None,
    inner: DecisionOrchestrator | None = None,
) -> RangeRecoveryOrchestrator:
    return RangeRecoveryOrchestrator(inner=inner, base_dir=base_dir)
