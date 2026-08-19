"""Phase 14.1 — central decision orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone

from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine
from tradingbot.ml.decision_engine.decision_policy import DecisionPolicy, DEFAULT_POLICY
from tradingbot.ml.decision_engine.decision_trace import build_trace
from tradingbot.ml.decision_engine.decision_types import FinalDecision, MarketContext
from tradingbot.ml.decision_engine.strategy_selector import select_engine, select_signal
from tradingbot.ml.decision_engine.vol_regime_branch import try_vol_regime_from_features


class DecisionOrchestrator:
    """
    Production decision brain — consumes market context and engine outputs,
    returns one unified explainable decision. No execution.
    """

    def __init__(
        self,
        *,
        policy: DecisionPolicy | None = None,
        confidence_engine: ConfidenceEngine | None = None,
        persist_traces: bool = False,
        base_dir: str | None = None,
    ) -> None:
        self.policy = policy or DEFAULT_POLICY
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.persist_traces = persist_traces
        self.base_dir = base_dir

    def decide(self, market_context: MarketContext) -> FinalDecision:
        ctx = market_context
        ts = ctx.timestamp or datetime.now(timezone.utc)

        if self.policy.vol_regime_enabled:
            vol_decision = try_vol_regime_from_features(ctx)
            if vol_decision is not None:
                self._maybe_persist(vol_decision, ctx)
                return vol_decision

        engine_id = select_engine(ctx.regime)
        selected = select_signal(ctx, engine_id)

        if engine_id is None or selected is None:
            trace = build_trace(
                context=ctx,
                engine_id=None,
                model_confidence=0.0,
                final_confidence=0.0,
                raw_action="HOLD",
                final_action="HOLD",
                policy_threshold=self.policy.min_confidence,
            )
            explanation = [
                f"regime {ctx.regime} blocks trading",
                "no engine selected",
            ]
            if ctx.regime == "HIGH_VOLATILITY":
                explanation.insert(0, "high volatility regime — HOLD")
            elif ctx.regime == "NO_TRADE":
                explanation.insert(0, "no-trade regime — HOLD")

            decision = FinalDecision(
                action="HOLD",
                engine=None,
                confidence=0.0,
                regime=ctx.regime,
                timestamp=ts,
                explanation=explanation,
                risk_hint=0.0,
                trace=trace,
                metadata={"blocked_regime": ctx.regime},
            )
            self._maybe_persist(decision, ctx)
            return decision

        raw_action = selected.signal
        model_conf = float(selected.confidence)
        final_conf = self.confidence_engine.from_context(ctx, model_conf)
        final_action = self.policy.apply(raw_action, final_conf)
        risk_hint = self.confidence_engine.risk_hint(final_conf)

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
        if model_conf >= self.policy.min_confidence:
            explanation.append("model confidence high")
        else:
            explanation.append("model confidence moderate")
        explanation.append("volatility acceptable" if final_conf >= self.policy.min_confidence else "confidence below policy gate")

        if final_action == "HOLD" and raw_action in ("BUY", "SELL"):
            reason = self.policy.rejection_reason(final_conf)
            if reason:
                explanation.append(reason)

        decision = FinalDecision(
            action=final_action,
            engine=engine_id,
            confidence=final_conf,
            regime=ctx.regime,
            timestamp=ts,
            explanation=explanation,
            risk_hint=risk_hint,
            trace=trace,
            metadata={
                "raw_engine_signal": raw_action,
                "model_confidence": model_conf,
                "model": selected.model,
                "probability": selected.probability,
            },
        )
        self._maybe_persist(decision, ctx)
        return decision

    def _maybe_persist(self, decision: FinalDecision, context: MarketContext) -> None:
        if not self.persist_traces:
            return
        from tradingbot.ml.decision_engine.decision_trace import append_decision_log, trace_record

        append_decision_log(trace_record(decision, context), base_dir=self.base_dir)
