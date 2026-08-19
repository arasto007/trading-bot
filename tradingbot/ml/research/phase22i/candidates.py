"""Phase 22I — research-only decision policy candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine, compute_market_quality, compute_regime_strength, clamp
from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy
from tradingbot.ml.decision_engine.decision_types import Action, MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.research.phase15i.recovery_adapter import RangeAwareConfidenceEngine, RangeRecoveryOrchestrator


@dataclass(frozen=True)
class PolicyCandidate:
    id: str
    title: str
    description: str
    engineering_type: str
    threshold_tuning: bool
    build_orchestrator: Callable[..., DecisionOrchestrator | RangeRecoveryOrchestrator]


class UniversalDirectionalRecovery(ConfidenceEngine):
    """Apply directional probability recovery for any actionable engine signal."""

    def from_context(self, context: MarketContext, model_confidence: float) -> float:
        regime = str(context.regime).upper()
        if regime in ("NO_TRADE", "HIGH_VOLATILITY"):
            return super().from_context(context, model_confidence)
        engine_id = select_engine(regime)
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


class RegimeStrengthFloorEngine(ConfidenceEngine):
    """Floor regime_strength when engine emits BUY/SELL to reduce over-compression."""

    floor: float = 0.65

    def from_context(self, context: MarketContext, model_confidence: float) -> float:
        engine_id = select_engine(context.regime)
        selected = select_signal(context, engine_id)
        regime_strength = context.regime_strength or compute_regime_strength(context.features, context.regime)
        if selected is not None and selected.signal in ("BUY", "SELL"):
            regime_strength = max(regime_strength, self.floor)
        market_quality = compute_market_quality(context)
        return self.compute(
            model_confidence=model_confidence,
            regime_strength=regime_strength,
            market_quality=market_quality,
        )


class EngineConfidencePolicy(DecisionPolicy):
    """Pass when engine confidence OR composite confidence meets threshold."""

    def apply(self, action: Action, confidence: float, *, model_confidence: float = 0.0) -> Action:
        if action not in ("BUY", "SELL"):
            return "HOLD"
        effective = max(confidence, model_confidence)
        if effective < self.min_confidence:
            return "HOLD"
        return action


class EngineConfidenceOrchestrator(DecisionOrchestrator):
    """DecisionPolicy uses max(composite, model) confidence — research only."""

    def decide(self, market_context: MarketContext):
        from datetime import datetime, timezone

        from tradingbot.ml.decision_engine.decision_trace import build_trace
        from tradingbot.ml.decision_engine.decision_types import FinalDecision

        ctx = market_context
        ts = ctx.timestamp or datetime.now(timezone.utc)
        engine_id = select_engine(ctx.regime)
        selected = select_signal(ctx, engine_id)

        if engine_id is None or selected is None:
            return super().decide(ctx)

        raw_action = selected.signal
        model_conf = float(selected.confidence)
        final_conf = self.confidence_engine.from_context(ctx, model_conf)
        if isinstance(self.policy, EngineConfidencePolicy):
            final_action = self.policy.apply(raw_action, final_conf, model_confidence=model_conf)
        else:
            final_action = self.policy.apply(raw_action, final_conf)

        trace = build_trace(
            context=ctx,
            engine_id=engine_id,
            model_confidence=model_conf,
            final_confidence=final_conf,
            raw_action=raw_action,
            final_action=final_action,
            policy_threshold=self.policy.min_confidence,
        )
        explanation: list[str] = []
        if ctx.regime == "TREND":
            explanation.append("trend regime confirmed")
        elif ctx.regime == "RANGE":
            explanation.append("range regime confirmed")
        explanation.append(f"selected engine {engine_id}")
        if max(final_conf, model_conf) >= self.policy.min_confidence:
            explanation.append("engine or composite confidence meets gate")
        else:
            explanation.append("confidence below policy gate")

        return FinalDecision(
            action=final_action,
            engine=engine_id,
            confidence=final_conf,
            regime=ctx.regime,
            timestamp=ts,
            explanation=explanation,
            risk_hint=self.confidence_engine.risk_hint(final_conf),
            trace=trace,
            metadata={
                "raw_engine_signal": raw_action,
                "model_confidence": model_conf,
                "model": selected.model,
                "probability": selected.probability,
            },
        )


class AlternateEngineOrchestrator(RangeRecoveryOrchestrator):
    """When primary engine HOLDs, promote alternate engine if strongly directional."""

    alt_prob_min: float = 0.55

    def decide(self, market_context: MarketContext):
        ctx = market_context
        primary_id = select_engine(ctx.regime)
        primary = select_signal(ctx, primary_id)
        if primary is not None and primary.signal in ("BUY", "SELL"):
            return self.inner.decide(ctx)

        alt = ctx.trend_signal if primary_id == "phase9_9" else ctx.range_signal
        if alt.signal in ("BUY", "SELL"):
            prob = float(alt.probability)
            directional = prob if alt.signal == "BUY" else 1.0 - prob
            if directional >= self.alt_prob_min:
                patched = MarketContext(
                    symbol=ctx.symbol,
                    timeframe=ctx.timeframe,
                    features=dict(ctx.features),
                    regime="TREND" if alt.model != "phase9_9" else "RANGE",
                    regime_strength=ctx.regime_strength,
                    range_signal=ctx.range_signal,
                    trend_signal=ctx.trend_signal,
                    volatility=ctx.volatility,
                    session=ctx.session,
                    timestamp=ctx.timestamp,
                )
                return self.inner.decide(patched)
        return self.inner.decide(ctx)


class SpreadAwareQualityEngine(ConfidenceEngine):
    """Skip market_quality penalty when spread is normal (<4 pips)."""

    def from_context(self, context: MarketContext, model_confidence: float) -> float:
        spread = float(context.features.get("spread_pips", 0.0))
        regime_strength = context.regime_strength or compute_regime_strength(context.features, context.regime)
        market_quality = 1.0 if spread < 4.0 else compute_market_quality(context)
        return self.compute(
            model_confidence=model_confidence,
            regime_strength=regime_strength,
            market_quality=market_quality,
        )


def _baseline_orchestrator(*, base_dir: str | None, policy: DecisionPolicy) -> RangeRecoveryOrchestrator:
    from tradingbot.ml.research.phase15i.recovery_adapter import build_range_recovery_orchestrator

    o = build_range_recovery_orchestrator(base_dir=base_dir)
    o.inner.policy = policy
    return o


def _wrap(inner: DecisionOrchestrator | RangeRecoveryOrchestrator) -> RangeRecoveryOrchestrator:
    if isinstance(inner, RangeRecoveryOrchestrator):
        return inner
    return RangeRecoveryOrchestrator(inner=inner)


def list_policy_candidates(*, policy: DecisionPolicy) -> list[PolicyCandidate]:
    return [
        PolicyCandidate(
            id="22I-BASELINE",
            title="Production baseline (Phase 22C + RangeRecovery)",
            description="Current RangeAwareConfidenceEngine + DecisionPolicy min_confidence from 22C.",
            engineering_type="baseline",
            threshold_tuning=False,
            build_orchestrator=lambda *, base_dir=None, policy=None, **kw: _baseline_orchestrator(
                base_dir=base_dir, policy=policy or DecisionPolicy(),
            ),
        ),
        PolicyCandidate(
            id="22I-001",
            title="Universal directional recovery",
            description="Extend directional probability recovery to all non-blocked regimes with actionable engine signal.",
            engineering_type="confidence_engine",
            threshold_tuning=False,
            build_orchestrator=lambda **kw: RangeRecoveryOrchestrator(
                inner=DecisionOrchestrator(
                    policy=policy,
                    confidence_engine=UniversalDirectionalRecovery(),
                    base_dir=kw.get("base_dir"),
                ),
            ),
        ),
        PolicyCandidate(
            id="22I-002",
            title="Regime strength floor on actionable signals",
            description="Floor regime_strength at 0.65 when engine emits BUY/SELL to prevent over-compression before policy gate.",
            engineering_type="confidence_engine",
            threshold_tuning=False,
            build_orchestrator=lambda **kw: RangeRecoveryOrchestrator(
                inner=DecisionOrchestrator(
                    policy=policy,
                    confidence_engine=RegimeStrengthFloorEngine(),
                    base_dir=kw.get("base_dir"),
                ),
            ),
        ),
        PolicyCandidate(
            id="22I-003",
            title="Engine-confidence policy gate",
            description="DecisionPolicy passes if max(composite_conf, model_confidence) >= threshold — avoids double compression rejection.",
            engineering_type="decision_policy",
            threshold_tuning=False,
            build_orchestrator=lambda **kw: RangeRecoveryOrchestrator(
                inner=EngineConfidenceOrchestrator(
                    policy=EngineConfidencePolicy(min_confidence=policy.min_confidence),
                    confidence_engine=RangeAwareConfidenceEngine(),
                    base_dir=kw.get("base_dir"),
                ),
            ),
        ),
        PolicyCandidate(
            id="22I-004",
            title="Alternate engine confirmation",
            description="When primary engine HOLDs, promote alternate engine if directional probability >= 0.55.",
            engineering_type="signal_confirmation",
            threshold_tuning=False,
            build_orchestrator=lambda **kw: AlternateEngineOrchestrator(
                inner=DecisionOrchestrator(
                    policy=policy,
                    confidence_engine=RangeAwareConfidenceEngine(),
                    base_dir=kw.get("base_dir"),
                ),
            ),
        ),
        PolicyCandidate(
            id="22I-005",
            title="Spread-aware market quality",
            description="Skip market_quality compression when spread < 4 pips (uses existing spread tiers from ConfidenceEngine).",
            engineering_type="confidence_engine",
            threshold_tuning=False,
            build_orchestrator=lambda **kw: RangeRecoveryOrchestrator(
                inner=DecisionOrchestrator(
                    policy=policy,
                    confidence_engine=SpreadAwareQualityEngine(),
                    base_dir=kw.get("base_dir"),
                ),
            ),
        ),
    ]


def top_five_candidates(*, policy: DecisionPolicy) -> list[PolicyCandidate]:
    all_c = list_policy_candidates(policy=policy)
    return [c for c in all_c if c.id != "22I-BASELINE"][:5]
