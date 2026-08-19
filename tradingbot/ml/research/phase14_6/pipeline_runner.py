"""Phase 14.6 — pipeline runner with injectable research calibration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase14_4.pipeline_simulator import (
    PipelineThresholds,
    simulate_trade_outcome,
    trade_metrics_from_records,
)
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod
from tradingbot.ml.research.phase14_6.config import DEFAULT_MAX_RISK_PERCENT, DEFAULT_QUALITY_THRESHOLD
from tradingbot.ml.research.phase14_6.research_calibrator import ResearchCalibratedAdapter, ResearchCalibrationPolicy
from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
from tradingbot.ml.risk_intelligence.risk_policy import RiskPolicy
from tradingbot.ml.risk_intelligence.risk_types import AccountState, HistoricalMetrics
from tradingbot.ml.risk_intelligence.validator import AdaptiveRiskAdapter
from tradingbot.ml.trade_quality.adapter import TradeQualityAdapter
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_policy import QualityPolicy
from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator


@dataclass(frozen=True)
class ResearchPipelineThresholds:
    confidence_threshold: float = 0.55
    quality_threshold: float = 0.50
    max_risk_percent: float = 0.50


def build_research_adapter(
    calibration_method: CalibrationMethod,
    *,
    thresholds: ResearchPipelineThresholds | None = None,
) -> TradeQualityAdapter:
    th = thresholds or ResearchPipelineThresholds()
    orchestrator = DecisionOrchestrator()
    decision_adapter = ResearchCalibratedAdapter(
        orchestrator,
        calibration_method=calibration_method,
        policy=ResearchCalibrationPolicy(min_calibrated_confidence=th.confidence_threshold),
    )
    history = HistoricalMetrics(engine_trade_count={"phase9_9": 3788, "trend_rf_v40": 1205})
    risk_engine = AdaptiveRiskEngine(policy=RiskPolicy(max_risk_percent=th.max_risk_percent))
    risk_adapter = AdaptiveRiskAdapter(
        decision_adapter,  # type: ignore[arg-type]
        risk_engine=risk_engine,
        account=AccountState(),
        history=history,
    )
    quality_engine = TradeQualityEngine(
        policy=QualityPolicy(threshold=th.quality_threshold),
        history=history,
    )
    return TradeQualityAdapter(risk_adapter, quality_engine=quality_engine)


def run_research_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    calibration_method: CalibrationMethod,
    confidence_threshold: float = 0.55,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    max_risk_percent: float = DEFAULT_MAX_RISK_PERCENT,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    th = ResearchPipelineThresholds(
        confidence_threshold=confidence_threshold,
        quality_threshold=quality_threshold,
        max_risk_percent=max_risk_percent,
    )
    adapter = build_research_adapter(calibration_method, thresholds=th)

    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None or trend_engine is None:
        range_engine, trend_engine = load_production_engines(candles, symbol=symbol, seed=seed)

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
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
        )
        calibrated, risk, quality = adapter.evaluate(ctx)
        raw_signal = str(calibrated.decision.metadata.get("raw_engine_signal", "HOLD"))
        conf = float(calibrated.final_confidence)

        risk_allowed = risk.allowed and risk.risk_percent > 0 and risk.risk_percent <= max_risk_percent
        quality_allowed = quality.allowed
        final_allowed = raw_signal in ("BUY", "SELL") and conf >= confidence_threshold and risk_allowed and quality_allowed

        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
        outcome = (
            simulate_trade_outcome(c, bar_idx, direction=raw_signal)
            if raw_signal in ("BUY", "SELL")
            else {"r_multiple": 0.0, "mfe": 0.0, "mae": 0.0}
        )

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
            {
                "timestamp": str(ts),
                "year": int(ts.year),
                "raw_signal": raw_signal,
                "confidence": conf,
                "raw_confidence": float(calibrated.raw_confidence.raw_value),
                "risk_percent": risk.risk_percent,
                "quality_score": quality.score,
                "allowed": final_allowed,
                "block_reason": block_reason,
                "engine": calibrated.decision.engine,
                "regime": calibrated.decision.regime,
                "r_multiple": outcome["r_multiple"],
                "mfe": outcome["mfe"],
                "mae": outcome["mae"],
            }
        )
    return records


def pipeline_metrics(records: list[dict[str, Any]], *, stride: int = 1) -> dict[str, Any]:
    base = trade_metrics_from_records(records)
    accepted = [r for r in records if r["allowed"]]
    conf_vals = [float(r["confidence"]) for r in records if r["raw_signal"] in ("BUY", "SELL")]
    from tradingbot.ml.research.phase14_6.confidence_distribution import distribution_stats

    return {
        **base,
        "effective_trades_est": int(base["trades"] * max(1, stride)),
        "accepted_trades": len(accepted),
        "confidence_distribution": distribution_stats(conf_vals),
    }
