"""Final shadow decision engine — ensemble orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_REJECT, DECISION_SELL, DECISION_WAIT
from tradingbot.ml.orchestrator.confidence_router import ConfidenceRouter
from tradingbot.ml.orchestrator.ensemble import EnsembleEngine
from tradingbot.ml.orchestrator.explain import build_reasoning
from tradingbot.ml.orchestrator.regime_gate import RegimeGate
from tradingbot.ml.orchestrator.risk_adjustment import RiskAdjustmentLayer
from tradingbot.ml.orchestrator.schema import (
    FinalDecision,
    OrchestratorConfig,
    OrchestratorSnapshot,
    RiskState,
    StrategyMode,
)
from tradingbot.ml.orchestrator.strategy_selector import StrategySelector


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class FinalDecisionEngine:
    """
    Merge rule, ML, hybrid, A/B, monitoring, and paper-trading inputs.

    Shadow-only — no execution calls.
    """

    config: OrchestratorConfig | None = None
    ensemble: EnsembleEngine | None = None
    risk_layer: RiskAdjustmentLayer | None = None
    regime_gate: RegimeGate | None = None
    confidence_router: ConfidenceRouter | None = None
    strategy_selector: StrategySelector | None = None

    def __post_init__(self) -> None:
        cfg = self.config or OrchestratorConfig()
        self.config = cfg
        self.ensemble = self.ensemble or EnsembleEngine(cfg)
        self.risk_layer = self.risk_layer or RiskAdjustmentLayer(cfg)
        self.regime_gate = self.regime_gate or RegimeGate()
        self.confidence_router = self.confidence_router or ConfidenceRouter()
        self.strategy_selector = self.strategy_selector or StrategySelector()

    def generate_final_decision(self, snapshot: OrchestratorSnapshot) -> FinalDecision:
        cfg = self.config
        assert cfg is not None
        ensemble = self.ensemble
        risk_layer = self.risk_layer
        regime_gate = self.regime_gate
        confidence_router = self.confidence_router
        strategy_selector = self.strategy_selector
        assert ensemble and risk_layer and regime_gate and confidence_router and strategy_selector

        strategy = strategy_selector.select(snapshot)
        contributions = ensemble.compute(snapshot)
        regime = regime_gate.evaluate(snapshot)
        risk = risk_layer.evaluate(snapshot, contributions.adjusted_score)

        score = contributions.adjusted_score * risk.score_multiplier

        if strategy == StrategyMode.SAFE_MODE.value:
            action = DECISION_WAIT
        elif regime.force_wait or risk.force_wait:
            action = DECISION_WAIT
        elif strategy == StrategyMode.RULE_ONLY.value:
            action = self._action_from_signal(contributions.rule_signal, cfg)
        elif strategy == StrategyMode.ML_ONLY.value:
            if not regime.allow_ml:
                action = DECISION_WAIT
            else:
                action = self._action_from_signal(contributions.ml_signal, cfg)
        elif strategy == StrategyMode.HYBRID.value:
            action = self._action_from_hybrid(snapshot, cfg)
        else:
            action = self._action_from_score(score, cfg)

        if risk.risk_state == RiskState.BLOCKED.value:
            action = DECISION_WAIT

        if action in (DECISION_BUY, DECISION_SELL) and abs(score) < cfg.min_score:
            action = DECISION_WAIT

        if regime.reduce_frequency and action in (DECISION_BUY, DECISION_SELL) and abs(score) < cfg.min_score + 0.05:
            action = DECISION_WAIT

        if snapshot.performance_state == "FAILED" and action in (DECISION_BUY, DECISION_SELL):
            action = DECISION_REJECT

        confidence = confidence_router.route(snapshot, score, strategy_mode=strategy)
        reasoning = build_reasoning(
            snapshot,
            contributions,
            action=action,
            confidence=confidence,
            active_strategy=strategy,
            regime=regime.regime,
            risk_reasons=risk.reasons,
            regime_reasons=regime.reasons,
        )

        trace = {
            "inputs": snapshot.to_dict(),
            "weights": {
                "ml_weight": contributions.ml_weight,
                "rule_weight": contributions.rule_weight,
                "hybrid_weight": contributions.hybrid_weight,
            },
            "intermediate": {
                "raw_score": contributions.raw_score,
                "adjusted_score": contributions.adjusted_score,
                "risk_multiplier": risk.score_multiplier,
                "final_score": round(score, 6),
            },
            "regime_gate": {
                "regime": regime.regime,
                "allow_ml": regime.allow_ml,
                "favor_rule": regime.favor_rule,
                "force_wait": regime.force_wait,
            },
            "risk_state": risk.risk_state,
            "strategy": strategy,
        }

        return FinalDecision(
            timestamp=snapshot.timestamp,
            symbol=snapshot.symbol,
            timeframe=snapshot.timeframe,
            action=action,
            confidence=confidence,
            active_strategy=strategy,
            reasoning=reasoning,
            risk_state=risk.risk_state,
            source_contributions=contributions,
            ensemble_score=round(score, 6),
            regime=regime.regime,
            trace=trace,
        )

    @staticmethod
    def _action_from_score(score: float, cfg: OrchestratorConfig) -> str:
        if score >= cfg.buy_threshold:
            return DECISION_BUY
        if score <= cfg.sell_threshold:
            return DECISION_SELL
        return DECISION_WAIT

    @staticmethod
    def _action_from_signal(signal: float, cfg: OrchestratorConfig) -> str:
        if signal >= cfg.buy_threshold:
            return DECISION_BUY
        if signal <= cfg.sell_threshold:
            return DECISION_SELL
        return DECISION_WAIT

    @staticmethod
    def _action_from_hybrid(snapshot: OrchestratorSnapshot, cfg: OrchestratorConfig) -> str:
        decision = snapshot.hybrid_decision.upper()
        if decision in (DECISION_BUY, DECISION_SELL):
            if snapshot.ml_prediction != 1 or snapshot.final_score < cfg.min_score:
                return DECISION_WAIT
            return decision
        return DECISION_WAIT
