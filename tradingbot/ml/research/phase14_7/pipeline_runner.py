"""Phase 14.7 — full Phase 14 pipeline runner."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_6.calibration_alternatives import CalibrationMethod
from tradingbot.ml.research.phase14_7.calibration_adapter import build_calibrated_adapter
from tradingbot.ml.research.phase14_7.config import (
    DEFAULT_MAX_RISK_PERCENT,
    DEFAULT_QUALITY_THRESHOLD,
    PIPELINE_FULL,
)
from tradingbot.ml.research.phase14_7.quality_adapter import build_quality_adapter
from tradingbot.ml.research.phase14_7.risk_adapter import build_risk_adapter
from tradingbot.ml.research.phase14_7.trade_tracker import build_trade_record, simulate_outcome


def run_full_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    calibration_method: CalibrationMethod,
    *,
    confidence_threshold: float,
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

    decision_adapter = build_calibrated_adapter(calibration_method, confidence_threshold=confidence_threshold)
    adapter = build_quality_adapter(build_risk_adapter(decision_adapter))

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

        risk_allowed = risk.allowed and risk.risk_percent > 0 and risk.risk_percent <= DEFAULT_MAX_RISK_PERCENT
        quality_allowed = quality.allowed
        final_allowed = (
            raw_signal in ("BUY", "SELL")
            and conf >= confidence_threshold
            and risk_allowed
            and quality_allowed
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
                pipeline=PIPELINE_FULL,
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
    return records
