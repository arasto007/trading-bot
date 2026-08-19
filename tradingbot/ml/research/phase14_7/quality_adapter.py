"""Phase 14.7 — trade quality layer wrapper (read-only on 14.3)."""

from __future__ import annotations

from tradingbot.ml.research.phase14_7.config import DEFAULT_QUALITY_THRESHOLD
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_policy import QualityPolicy


def build_quality_adapter(risk_adapter: AdaptiveRiskAdapter) -> TradeQualityAdapter:
    quality_engine = TradeQualityEngine(
        policy=QualityPolicy(threshold=DEFAULT_QUALITY_THRESHOLD),
        history=risk_adapter.history,
    )
    return TradeQualityAdapter(risk_adapter, quality_engine=quality_engine)
