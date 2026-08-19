"""Phase 14.9 — adaptive router with dynamic engine selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from tradingbot.ml.confidence_engine.validator import raw_confidence_from_decision
from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine, compute_market_quality, compute_regime_strength
from tradingbot.ml.decision_engine.decision_types import FinalDecision, MarketContext
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.research.phase14_7.config import DEFAULT_MAX_RISK_PERCENT, DEFAULT_QUALITY_THRESHOLD
from tradingbot.ml.research.phase14_7.quality_adapter import build_quality_adapter
from tradingbot.ml.research.phase14_7.risk_adapter import build_risk_adapter
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.research.phase14_7.trade_tracker import build_trade_record, simulate_outcome
from tradingbot.ml.research.phase14_9.dynamic_engine_weight import EngineWeights, compute_engine_weights
from tradingbot.ml.research.phase14_9.config import RANGE_ENGINE_ID, TREND_ENGINE_ID
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


@dataclass
class AdaptiveRouterDecision:
    """Research decision with adaptive engine selection."""

    decision: FinalDecision
    weights: EngineWeights
    final_confidence: float
    calibrated_confidence: float
    final_action: str


class AdaptiveRouterAdapter:
    """Research-only router: dynamic weights → engine → Platt calibration → risk → quality."""

    def __init__(
        self,
        *,
        calibration_method: CalibrationMethod,
        confidence_threshold: float = 0.30,
    ) -> None:
        self.calibration_method = calibration_method
        self.policy = ResearchCalibrationPolicy(min_calibrated_confidence=confidence_threshold)
        self.confidence_engine = ConfidenceEngine()
        self._inner = ResearchCalibratedAdapter(
            DecisionOrchestrator(),
            calibration_method=calibration_method,
            policy=self.policy,
        )
        self._quality = build_quality_adapter(build_risk_adapter(self._inner))

    def route(self, context: MarketContext, row: pd.Series) -> AdaptiveRouterDecision:
        regime = rule_classify_row(row)
        weights = compute_engine_weights(row, regime=regime)
        engine_id = weights.selected_engine()

        if engine_id is None:
            ts = context.timestamp or datetime.now(timezone.utc)
            blocked = FinalDecision(
                action="HOLD",
                engine=None,
                confidence=0.0,
                regime=regime,
                timestamp=ts,
                explanation=[f"regime {regime} blocks trading"],
                risk_hint=0.0,
                trace=[],
                metadata={"blocked_regime": regime, "adaptive_weights": weights.__dict__},
            )
            return AdaptiveRouterDecision(
                decision=blocked, weights=weights, final_confidence=0.0,
                calibrated_confidence=0.0, final_action="HOLD",
            )

        selected = context.trend_signal if engine_id == TREND_ENGINE_ID else context.range_signal
        raw_action = selected.signal
        model_conf = float(selected.confidence)
        regime_strength = context.regime_strength or compute_regime_strength(context.features, regime)
        market_quality = compute_market_quality(context)
        composed = self.confidence_engine.compute(
            model_confidence=model_conf,
            regime_strength=regime_strength,
            market_quality=market_quality,
        )
        ts = context.timestamp or datetime.now(timezone.utc)
        decision = FinalDecision(
            action=raw_action if raw_action in ("BUY", "SELL") else "HOLD",
            engine=engine_id,
            confidence=composed,
            regime=regime,
            timestamp=ts,
            explanation=[f"adaptive route to {engine_id}", f"weights trend={weights.trend_weight} range={weights.range_weight}"],
            risk_hint=self.confidence_engine.risk_hint(composed),
            trace=[],
            metadata={
                "raw_engine_signal": raw_action,
                "probability": float(selected.probability),
                "adaptive_weights": {
                    "trend": weights.trend_weight,
                    "range": weights.range_weight,
                },
            },
        )
        raw = raw_confidence_from_decision(decision, context)
        calibrated = self.calibration_method.calibrate(raw)
        final_conf = calibrated.calibrated_value
        if self.policy.passes_gate(final_conf) and raw.engine_signal in ("BUY", "SELL"):
            final_action = raw.engine_signal
        else:
            final_action = "HOLD"
        decision = FinalDecision(
            action=final_action,
            engine=engine_id,
            confidence=final_conf,
            regime=regime,
            timestamp=ts,
            explanation=decision.explanation + calibrated.explanation,
            risk_hint=decision.risk_hint,
            trace=decision.trace,
            metadata=decision.metadata,
        )
        return AdaptiveRouterDecision(
            decision=decision,
            weights=weights,
            final_confidence=final_conf,
            calibrated_confidence=final_conf,
            final_action=final_action,
        )

    def evaluate(self, context: MarketContext, row: pd.Series):
        routed = self.route(context, row)
        from tradingbot.ml.confidence_engine.validator import CalibratedDecision

        cal_dec = CalibratedDecision(
            decision=routed.decision,
            raw_confidence=raw_confidence_from_decision(routed.decision, context),
            calibrated=self.calibration_method.calibrate(
                raw_confidence_from_decision(routed.decision, context)
            ),
            final_action=routed.final_action,
            final_confidence=routed.final_confidence,
        )
        from tradingbot.ml.risk_intelligence.validator import risk_context_from_calibrated

        risk_ctx = risk_context_from_calibrated(context, cal_dec, account=self._quality.risk_adapter.account, history=self._quality.risk_adapter.history)
        risk = self._quality.risk_adapter.risk_engine.recommend(risk_ctx)
        from tradingbot.ml.trade_quality.adapter import build_quality_context

        qctx = build_quality_context(context, cal_dec, risk, rr_ratio=self._quality.rr_ratio)
        quality = self._quality.quality_engine.evaluate(qctx)
        return cal_dec, risk, quality, routed


def run_adaptive_router_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method: CalibrationMethod,
    *,
    confidence_threshold: float = 0.30,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

    adapter = AdaptiveRouterAdapter(
        calibration_method=calibration_method,
        confidence_threshold=confidence_threshold,
    )

    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    records: list[dict[str, Any]] = []
    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=range_engine, trend_engine=trend_engine,
        )
        calibrated, risk, quality, routed = adapter.evaluate(ctx, row)
        raw_signal = str(calibrated.decision.metadata.get("raw_engine_signal", "HOLD"))
        conf = float(calibrated.final_confidence)

        risk_allowed = risk.allowed and risk.risk_percent > 0 and risk.risk_percent <= DEFAULT_MAX_RISK_PERCENT
        quality_allowed = quality.allowed
        final_allowed = (
            raw_signal in ("BUY", "SELL") and conf >= confidence_threshold
            and risk_allowed and quality_allowed
        )

        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
        outcome = simulate_outcome(c, bar_idx, raw_signal)

        block_reason = None
        if not final_allowed:
            if raw_signal not in ("BUY", "SELL"):
                block_reason = "hold_action"
            elif conf < confidence_threshold:
                block_reason = "confidence"
            elif not risk_allowed:
                block_reason = "risk"
            elif not quality_allowed:
                block_reason = "quality"

        records.append(
            build_trade_record(
                timestamp=str(ts),
                year=int(ts.year),
                pipeline="phase14_9_adaptive",
                raw_signal=raw_signal,
                allowed=final_allowed,
                block_reason=block_reason,
                engine=calibrated.decision.engine,
                regime=calibrated.decision.regime,
                confidence=conf,
                raw_confidence=float(calibrated.raw_confidence.raw_value),
                calibrated_confidence=conf,
                risk_percent=float(risk.risk_percent),
                quality_score=float(quality.score),
                r_multiple=outcome["r_multiple"],
                mfe=outcome["mfe"],
                mae=outcome["mae"],
            )
        )
        records[-1]["trend_weight"] = routed.weights.trend_weight
        records[-1]["range_weight"] = routed.weights.range_weight
    return records
