"""Phase 14.3 — trade quality integration adapter."""

from __future__ import annotations

from tradingbot.ml.confidence_engine.validator import CalibratedDecision
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics, RiskRecommendation
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter
from tradingbot.ml.trade_quality.liquidity_quality import classify_spread
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_types import QualityScore, TradeQualityContext
from tradingbot.ml.trade_quality.regime_quality import VOL_REGIME_ENGINE
from tradingbot.strategies.vol_regime_signal import DEFAULT_TP_RR

DEFAULT_RR_RATIO = 2.0


def build_quality_context(
    market: MarketContext,
    calibrated: CalibratedDecision,
    risk: RiskRecommendation,
    *,
    rr_ratio: float = DEFAULT_RR_RATIO,
) -> TradeQualityContext:
    spread = float(market.features.get("spread_pips", 0.0))
    engine = calibrated.decision.engine
    effective_rr = DEFAULT_TP_RR if engine == VOL_REGIME_ENGINE else rr_ratio
    return TradeQualityContext(
        market=market,
        calibrated=calibrated,
        risk=risk,
        engine=engine,
        regime=calibrated.decision.regime,
        action=str(calibrated.final_action),
        confidence=float(calibrated.final_confidence),
        risk_percent=float(risk.risk_percent),
        atr_percentile=float(market.volatility),
        spread_pips=spread,
        spread_class=classify_spread(spread),
        session=market.session,
        rr_ratio=effective_rr,
    )


class TradeQualityAdapter:
    """
    Chains AdaptiveRiskAdapter output → trade quality evaluation.
    Does not modify Phase 14.1 / 14.2A / 14.2B modules.
    """

    def __init__(
        self,
        risk_adapter: AdaptiveRiskAdapter,
        *,
        quality_engine: TradeQualityEngine | None = None,
        rr_ratio: float = DEFAULT_RR_RATIO,
    ) -> None:
        self.risk_adapter = risk_adapter
        self.quality_engine = quality_engine or TradeQualityEngine(
            history=risk_adapter.history,
        )
        self.rr_ratio = rr_ratio

    def evaluate(
        self,
        market: MarketContext,
    ) -> tuple[CalibratedDecision, RiskRecommendation, QualityScore]:
        calibrated, risk = self.risk_adapter.evaluate(market)
        ctx = build_quality_context(
            market,
            calibrated,
            risk,
            rr_ratio=self.rr_ratio,
        )
        quality = self.quality_engine.evaluate(ctx)
        return calibrated, risk, quality
