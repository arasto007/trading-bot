"""Phase 14.2B — adaptive risk intelligence engine."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.confidence_risk_mapper import confidence_risk_multiplier
from tradingbot.ml.risk_intelligence.drawdown_controller import drawdown_risk_multiplier
from tradingbot.ml.risk_intelligence.engine_performance import engine_performance_factor
from tradingbot.ml.risk_intelligence.regime_risk_adjuster import regime_risk_multiplier
from tradingbot.ml.risk_intelligence.risk_policy import DEFAULT_RISK_POLICY, RiskPolicy
from tradingbot.ml.risk_intelligence.risk_types import AdaptiveRiskContext, RiskRecommendation
from tradingbot.ml.risk_intelligence.session_risk_adjuster import normalize_session, session_risk_multiplier
from tradingbot.ml.risk_intelligence.volatility_risk_adjuster import volatility_risk_multiplier


class AdaptiveRiskEngine:
    """
    Computes intelligent risk recommendations.
    RiskGate remains the final authority — this layer only recommends.
    """

    def __init__(self, *, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or DEFAULT_RISK_POLICY

    def recommend(self, context: AdaptiveRiskContext) -> RiskRecommendation:
        trace: list[str] = []
        ctx = context

        if str(ctx.action).upper() not in ("BUY", "SELL"):
            return RiskRecommendation(
                allowed=False,
                risk_percent=0.0,
                multiplier=0.0,
                confidence_factor=0.0,
                regime_factor=0.0,
                volatility_factor=0.0,
                session_factor=0.0,
                drawdown_factor=0.0,
                engine_factor=0.0,
                reason="HOLD action — no risk allocated",
                trace=["Action HOLD — skip risk"],
                blocked_by="hold_action",
            )

        conf_factor, conf_label = confidence_risk_multiplier(ctx.calibrated_confidence)
        trace.append(conf_label)
        if conf_factor <= 0.0:
            return self._blocked(ctx, conf_factor, conf_label, trace, "low_confidence")

        regime_factor, regime_label, regime_blocked = regime_risk_multiplier(ctx.regime)
        trace.append(regime_label)
        if regime_blocked:
            return self._blocked(ctx, 0.0, regime_label, trace, "regime")

        vol_factor, vol_label, vol_blocked = volatility_risk_multiplier(ctx.atr_percentile)
        trace.append(vol_label)
        if vol_blocked:
            return self._blocked(ctx, 0.0, vol_label, trace, "volatility")

        session_factor, session_label = session_risk_multiplier(ctx.session)
        trace.append(session_label)

        dd_factor, dd_label, dd_blocked = drawdown_risk_multiplier(ctx.account.drawdown_pct)
        trace.append(dd_label)
        if dd_blocked:
            return self._blocked(ctx, 0.0, dd_label, trace, "drawdown")

        engine_factor, engine_label = engine_performance_factor(ctx.engine, ctx.history)
        trace.append(engine_label)

        multiplier = conf_factor * regime_factor * vol_factor * session_factor * dd_factor * engine_factor
        raw_risk = self.policy.base_risk_percent * multiplier
        risk_percent = self.policy.clamp_risk(raw_risk)

        session_name = normalize_session(ctx.session)
        reason = self._build_reason(ctx, session_name, risk_percent)
        trace.append(f"Base risk {self.policy.base_risk_percent}% × {multiplier:.2f} = {risk_percent:.4f}%")
        trace.append("RiskGate remains final authority")

        allowed = risk_percent > 0.0
        return RiskRecommendation(
            allowed=allowed,
            risk_percent=round(risk_percent, 4),
            multiplier=round(multiplier, 4),
            confidence_factor=conf_factor,
            regime_factor=regime_factor,
            volatility_factor=vol_factor,
            session_factor=session_factor,
            drawdown_factor=dd_factor,
            engine_factor=engine_factor,
            reason=reason,
            trace=trace,
            blocked_by=None if allowed else "zero_risk",
        )

    def _blocked(
        self,
        ctx: AdaptiveRiskContext,
        conf_factor: float,
        label: str,
        trace: list[str],
        blocked_by: str,
    ) -> RiskRecommendation:
        return RiskRecommendation(
            allowed=False,
            risk_percent=0.0,
            multiplier=0.0,
            confidence_factor=conf_factor,
            regime_factor=0.0,
            volatility_factor=0.0,
            session_factor=0.0,
            drawdown_factor=0.0,
            engine_factor=0.0,
            reason=f"Risk blocked: {label}",
            trace=trace,
            blocked_by=blocked_by,
        )

    def _build_reason(self, ctx: AdaptiveRiskContext, session_name: str, risk_percent: float) -> str:
        conf = ctx.calibrated_confidence
        regime = ctx.regime
        if conf >= 0.75 and regime == "TREND":
            return f"High confidence {regime} {session_name} setup @ {risk_percent:.2f}%"
        if conf >= 0.65:
            return f"Moderate confidence {regime} {session_name} @ {risk_percent:.2f}%"
        return f"Conservative {regime} {session_name} risk @ {risk_percent:.2f}%"
