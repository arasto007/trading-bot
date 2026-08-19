"""Phase 14.7 — Phase 9.9-only baseline runner."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range
from tradingbot.ml.research.phase14_7.config import PHASE99_MIN_CONFIDENCE, PIPELINE_BASELINE
from tradingbot.ml.research.phase14_7.trade_tracker import build_trade_record, simulate_outcome


def run_baseline_pipeline(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    trend_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    min_confidence: float = PHASE99_MIN_CONFIDENCE,
) -> list[dict[str, Any]]:
    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None:
        range_engine, _ = load_production_engines(candles, symbol=symbol, seed=seed)

    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

    records: list[dict[str, Any]] = []
    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        regime = rule_classify_row(row)
        ev = range_engine.evaluate(row=row_for_phase99_range(row))
        signal = str(ev.get("signal", "HOLD"))
        conf = float(ev.get("confidence", 0.0))
        allowed = signal in ("BUY", "SELL") and conf >= min_confidence

        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
        outcome = simulate_outcome(c, bar_idx, signal)

        block_reason = None
        if not allowed:
            block_reason = "hold_action" if signal not in ("BUY", "SELL") else "confidence"

        records.append(
            build_trade_record(
                timestamp=str(ts),
                year=int(ts.year),
                pipeline=PIPELINE_BASELINE,
                raw_signal=signal,
                allowed=allowed,
                block_reason=block_reason,
                engine="phase9_9",
                regime=regime,
                confidence=conf,
                raw_confidence=conf,
                r_multiple=outcome["r_multiple"],
                mfe=outcome["mfe"],
                mae=outcome["mae"],
            )
        )
    return records
