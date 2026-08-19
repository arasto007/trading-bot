"""Phase 14.7 — Phase 13.10 regime router runner."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.config import PIPELINE_ROUTER, ROUTER_MIN_CONFIDENCE
from tradingbot.ml.research.phase14_7.trade_tracker import build_trade_record, simulate_outcome


def run_router_pipeline(
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
    min_confidence: float = ROUTER_MIN_CONFIDENCE,
) -> list[dict[str, Any]]:
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
        decision = orchestrator.decide(ctx)
        raw_signal = str(decision.metadata.get("raw_engine_signal", decision.action))
        conf = float(decision.confidence)
        allowed = decision.action in ("BUY", "SELL") and conf >= min_confidence

        ts = pd.to_datetime(row["timestamp"], utc=True)
        bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
        direction = decision.action if allowed else raw_signal
        outcome = simulate_outcome(c, bar_idx, direction if direction in ("BUY", "SELL") else "HOLD")

        block_reason = None
        if not allowed:
            if decision.action not in ("BUY", "SELL"):
                block_reason = "hold_action"
            else:
                block_reason = "confidence"

        records.append(
            build_trade_record(
                timestamp=str(ts),
                year=int(ts.year),
                pipeline=PIPELINE_ROUTER,
                raw_signal=raw_signal,
                allowed=allowed,
                block_reason=block_reason,
                engine=decision.engine,
                regime=decision.regime,
                confidence=conf,
                raw_confidence=conf,
                r_multiple=outcome["r_multiple"] if allowed else outcome["r_multiple"],
                mfe=outcome["mfe"],
                mae=outcome["mae"],
            )
        )
    return records
