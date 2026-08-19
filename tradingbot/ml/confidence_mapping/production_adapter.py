"""Phase 15H — production adapter: map confidence before RiskGate."""

from __future__ import annotations

import threading
from typing import Any

from tradingbot.ml.confidence_engine.validator import CalibratedDecision
from tradingbot.ml.confidence_mapping.confidence_mapper import ConfidenceMapper
from tradingbot.ml.confidence_mapping.equivalence_solver import collect_empirical_pairs, solve_mapping_curve
from tradingbot.ml.confidence_mapping.mapping_trace import build_mapping_trace
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics, RiskRecommendation
from tradingbot.ml.risk_intelligence.validator import risk_context_from_calibrated

_mapper_lock = threading.Lock()
_mapper_cache: dict[str, ConfidenceMapper] = {}


def _with_mapped_confidence(cal: CalibratedDecision, mapped: float) -> CalibratedDecision:
    return CalibratedDecision(
        decision=cal.decision,
        raw_confidence=cal.raw_confidence,
        calibrated=cal.calibrated,
        final_action=cal.final_action,
        final_confidence=float(mapped),
        calibration_trace=cal.calibration_trace,
    )


class MappedProductionRiskAdapter:
    """
    Decision → Calibration → ConfidenceMapper → Risk (unchanged RiskGate).

    Duck-types AdaptiveRiskAdapter for TradeQualityAdapter.
    """

    def __init__(
        self,
        calibration_adapter: Any,
        mapper: ConfidenceMapper,
        *,
        risk_engine: AdaptiveRiskEngine | None = None,
        account: AccountState | None = None,
        history: HistoricalMetrics | None = None,
    ) -> None:
        self.calibration_adapter = calibration_adapter
        self.mapper = mapper
        self.risk_engine = risk_engine or AdaptiveRiskEngine()
        self.account = account or AccountState()
        self.history = history or HistoricalMetrics()
        self.last_mapping_trace: dict[str, Any] | None = None

    def decide(self, market: MarketContext) -> CalibratedDecision:
        """Alias for calibration decide — used when adapter is chained as decision layer."""
        return self.calibration_adapter.decide(market)

    def evaluate(self, market: MarketContext) -> tuple[CalibratedDecision, RiskRecommendation]:
        calibrated = self.calibration_adapter.decide(market)
        frozen_conf = float(calibrated.final_confidence)
        mapped_conf = self.mapper.map(frozen_conf)
        self.last_mapping_trace = build_mapping_trace(
            frozen=frozen_conf,
            mapped=mapped_conf,
            stage="pre_risk",
            engine=calibrated.decision.engine,
            action=calibrated.final_action,
        )
        mapped_cal = _with_mapped_confidence(calibrated, mapped_conf)
        risk_ctx = risk_context_from_calibrated(
            market,
            mapped_cal,
            account=self.account,
            history=self.history,
        )
        recommendation = self.risk_engine.recommend(risk_ctx)
        return mapped_cal, recommendation


def build_confidence_mapper(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    days: int = 180,
) -> ConfidenceMapper:
    cache_key = f"{base_dir}:{symbol}:{timeframe}:{seed}:{days}"
    with _mapper_lock:
        if cache_key in _mapper_cache:
            return _mapper_cache[cache_key]

        candles = CandleStore(base_dir).load(symbol, timeframe)
        dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
        if candles is None or candles.empty or dataset is None or dataset.empty:
            from tradingbot.ml.confidence_mapping.mapping_types import MappingAnchor, MappingCurve
            curve = MappingCurve(
                anchors=[
                    MappingAnchor(0.0, 0.0, "fallback"),
                    MappingAnchor(0.50144, 0.767421, "phase15g_fallback"),
                ],
                frozen_ceiling=0.50144,
                research_ceiling=0.767421,
            )
            mapper = ConfidenceMapper(curve)
        else:
            pairs = collect_empirical_pairs(
                candles, dataset,
                base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed, days=days,
            )
            curve = solve_mapping_curve(pairs, base_dir=base_dir)
            mapper = ConfidenceMapper(curve)

        _mapper_cache[cache_key] = mapper
        return mapper


def build_mapped_production_risk(
    calibration_adapter: Any,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    risk_engine: AdaptiveRiskEngine | None = None,
    account: AccountState | None = None,
    history: HistoricalMetrics | None = None,
) -> MappedProductionRiskAdapter:
    mapper = build_confidence_mapper(
        base_dir=base_dir, symbol=symbol, timeframe=timeframe, seed=seed,
    )
    return MappedProductionRiskAdapter(
        calibration_adapter,
        mapper,
        risk_engine=risk_engine,
        account=account,
        history=history,
    )
