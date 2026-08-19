"""Phase 14.7 — adaptive risk layer wrapper (read-only on 14.2B)."""

from __future__ import annotations

from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter
from tradingbot.ml.research.phase14_7.config import DEFAULT_MAX_RISK_PERCENT
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.risk_policy import RiskPolicy
from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter


def build_risk_adapter(decision_adapter: ResearchCalibratedAdapter) -> AdaptiveRiskAdapter:
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v40": 1205})
    risk_engine = AdaptiveRiskEngine(policy=RiskPolicy(max_risk_percent=DEFAULT_MAX_RISK_PERCENT))
    return AdaptiveRiskAdapter(
        decision_adapter,  # type: ignore[arg-type]
        risk_engine=risk_engine,
        account=AccountState(),
        history=history,
    )
