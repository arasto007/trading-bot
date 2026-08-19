"""Phase 14.3 — trade quality intelligence engine."""

from __future__ import annotations

from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics
from tradingbot.ml.trade_quality.engine_history import engine_history_modifier
from tradingbot.ml.trade_quality.liquidity_quality import liquidity_quality_score
from tradingbot.ml.trade_quality.quality_policy import (
    DEFAULT_QUALITY_POLICY,
    QUALITY_THRESHOLD,
    WEIGHTS,
    QualityPolicy,
    score_to_grade,
)
from tradingbot.ml.trade_quality.quality_types import QualityScore, TradeQualityContext
from tradingbot.ml.trade_quality.regime_quality import regime_quality_score
from tradingbot.ml.trade_quality.rr_quality import rr_quality_score
from tradingbot.ml.trade_quality.signal_quality import signal_quality_score
from tradingbot.ml.trade_quality.timing_quality import timing_quality_score
from tradingbot.ml.trade_quality.volatility_quality import volatility_quality_score


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


class TradeQualityEngine:
    """Evaluates whether a trade opportunity has sufficient quality to proceed."""

    def __init__(
        self,
        *,
        policy: QualityPolicy | None = None,
        history: HistoricalMetrics | None = None,
    ) -> None:
        self.policy = policy or DEFAULT_QUALITY_POLICY
        self.history = history

    def evaluate(self, context: TradeQualityContext) -> QualityScore:
        trace: list[str] = []
        ctx = context

        if str(ctx.action).upper() not in ("BUY", "SELL"):
            return self._blocked(ctx, {}, "HOLD action", trace, "hold_action")

        if not ctx.risk.allowed or ctx.risk_percent <= 0:
            return self._blocked(ctx, {}, "risk not allowed", trace, "risk_blocked")

        sig, sig_label = signal_quality_score(ctx.confidence)
        trace.append(f"signal: {sig_label}")
        if sig <= 0:
            return self._blocked(ctx, {"signal": sig}, sig_label, trace, "signal")

        reg, reg_label = regime_quality_score(ctx.engine, ctx.regime)
        trace.append(f"regime: {reg_label}")
        if reg <= 0:
            return self._blocked(ctx, {"signal": sig, "regime": reg}, reg_label, trace, "regime")

        rr, rr_label = rr_quality_score(ctx.rr_ratio, engine_id=ctx.engine)
        trace.append(f"rr: {rr_label}")

        vol, vol_label = volatility_quality_score(ctx.atr_percentile)
        trace.append(f"volatility: {vol_label}")
        if vol <= 0:
            return self._blocked(
                ctx,
                {"signal": sig, "regime": reg, "rr": rr, "volatility": vol},
                vol_label,
                trace,
                "volatility",
            )

        liq, liq_label, _ = liquidity_quality_score(ctx.spread_pips)
        trace.append(f"liquidity: {liq_label}")
        if liq <= 0:
            return self._blocked(
                ctx,
                {"signal": sig, "regime": reg, "rr": rr, "volatility": vol, "liquidity": liq},
                liq_label,
                trace,
                "liquidity",
            )

        sess, sess_label = timing_quality_score(ctx.session)
        trace.append(f"session: {sess_label}")

        components = {
            "signal": sig,
            "regime": reg,
            "rr": rr,
            "volatility": vol,
            "liquidity": liq,
            "session": sess,
        }

        weighted = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
        hist_factor, hist_label = engine_history_modifier(ctx.engine, self.history)
        trace.append(f"history: {hist_label}")

        score = clamp(weighted * hist_factor)
        grade = score_to_grade(score)
        allowed = self.policy.passes(score) and rr > 0 and liq > 0 and vol > 0

        reason = self._build_reason(ctx, score, allowed)
        trace.append(f"weighted score {weighted:.4f} × history {hist_factor:.2f} = {score:.4f}")
        trace.append(f"threshold {QUALITY_THRESHOLD} — {'ALLOW' if allowed else 'BLOCK'}")
        trace.append("RiskGate remains final authority")

        return QualityScore(
            allowed=allowed,
            score=round(score, 4),
            grade=grade,
            components=components,
            reason=reason,
            trace=trace,
            blocked_by=None if allowed else "below_threshold",
        )

    def _blocked(
        self,
        ctx: TradeQualityContext,
        components: dict[str, float],
        label: str,
        trace: list[str],
        blocked_by: str,
    ) -> QualityScore:
        trace.append(f"BLOCKED: {label}")
        return QualityScore(
            allowed=False,
            score=0.0,
            grade="D",
            components=components,
            reason=f"Trade blocked: {label}",
            trace=trace,
            blocked_by=blocked_by,
        )

    def _build_reason(self, ctx: TradeQualityContext, score: float, allowed: bool) -> str:
        if not allowed:
            return f"Quality {score:.2f} below threshold {self.policy.threshold}"
        if ctx.regime == "TREND" and score >= 0.8:
            return "Strong trend setup with valid RR"
        if ctx.regime == "RANGE" and score >= 0.75:
            return "Solid range setup with acceptable liquidity"
        return f"Quality {score:.2f} meets threshold — proceed to RiskGate"
