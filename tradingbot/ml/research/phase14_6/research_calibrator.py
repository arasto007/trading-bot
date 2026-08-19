"""Phase 14.6 — research calibration adapter (read-only on production core)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.confidence_engine.calibration_trace import build_calibration_trace
from tradingbot.ml.confidence_engine.calibration_types import RawConfidence
from tradingbot.ml.confidence_engine.validator import CalibratedDecision, raw_confidence_from_decision
from tradingbot.ml.decision_engine.decision_types import MarketContext
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.research.phase14_4.pipeline_simulator import simulate_trade_outcome
from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod, CalibrationSample


@dataclass
class ResearchCalibrationPolicy:
    min_calibrated_confidence: float = 0.55

    def passes_gate(self, confidence: float) -> bool:
        return float(confidence) >= self.min_calibrated_confidence


class ResearchCalibratedAdapter:
    """Injectable research calibrator — same interface as CalibratedDecisionAdapter."""

    def __init__(
        self,
        orchestrator: DecisionOrchestrator,
        *,
        calibration_method: CalibrationMethod,
        policy: ResearchCalibrationPolicy | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.calibration_method = calibration_method
        self.policy = policy or ResearchCalibrationPolicy()

    def decide(self, context: MarketContext) -> CalibratedDecision:
        decision = self.orchestrator.decide(context)
        raw = raw_confidence_from_decision(decision, context)
        calibrated = self.calibration_method.calibrate(raw)
        engine_signal = raw.engine_signal
        final_conf = calibrated.calibrated_value
        if self.policy.passes_gate(final_conf) and engine_signal in ("BUY", "SELL"):
            final_action = engine_signal
        else:
            final_action = "HOLD"

        cal_trace = build_calibration_trace(raw, calibrated, adjustment_lines=calibrated.adjustments)
        return CalibratedDecision(
            decision=decision,
            raw_confidence=raw,
            calibrated=calibrated,
            final_action=final_action,
            final_confidence=final_conf,
            calibration_trace=cal_trace,
        )


def build_calibration_samples(
    candles,
    dataset,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine=None,
    trend_engine=None,
    unified=None,
) -> list[CalibrationSample]:
    """Chronological samples with trade outcomes for probability calibration fit."""
    import pandas as pd

    from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

    orchestrator = DecisionOrchestrator()
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    samples: list[CalibrationSample] = []
    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        decision = orchestrator.decide(ctx)
        raw = raw_confidence_from_decision(decision, ctx)
        outcome = None
        if raw.engine_signal in ("BUY", "SELL"):
            ts = pd.to_datetime(row["timestamp"], utc=True)
            bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
            sim = simulate_trade_outcome(c, bar_idx, direction=raw.engine_signal)
            outcome = 1 if float(sim["r_multiple"]) > 0 else 0
        samples.append(
            CalibrationSample(
                raw=raw,
                outcome=outcome,
                timestamp=str(ctx.timestamp),
            )
        )
    return samples
