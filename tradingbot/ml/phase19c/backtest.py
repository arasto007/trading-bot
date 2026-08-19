"""Phase 19C — filtered production pipeline backtest."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import build_market_context
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase19a.backtest import _duration_bars
from tradingbot.ml.phase19a.config import DEFAULT_STRIDE, DEFAULT_WARMUP
from tradingbot.ml.phase19c.filters import (
    ProfitabilityFilterSettings,
    apply_profitability_filters,
    load_filter_settings,
)
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase14_7.trade_tracker import simulate_outcome
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def run_filtered_backtest(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = DEFAULT_STRIDE,
    warmup: int = DEFAULT_WARMUP,
    filter_settings: ProfitabilityFilterSettings | None = None,
) -> dict[str, Any]:
    """
    Chronological backtest on production stack with Phase 19C profitability filters.
    Simulation only — no order_send.
    """
    settings = filter_settings or load_filter_settings()
    window = prepare_calibration_candles(candles, days=days)
    unified = attach_top5_features(build_unified_frame(window, dataset))

    c = window.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()
    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        range_inner, trend_inner = adapter._engine_inners()  # noqa: SLF001

        records: list[dict[str, Any]] = []
        filter_blocks = 0
        start = max(warmup, 0)
        for i in range(start, len(unified), max(1, stride)):
            row = unified.iloc[i]
            regime = rule_classify_row(row)
            ctx = build_market_context(
                row,
                symbol=symbol,
                timeframe=timeframe,
                range_engine=range_inner,
                trend_engine=trend_inner,
            )
            calibrated, risk, quality = stack.quality.evaluate(ctx)

            action = str(calibrated.final_action)
            if action not in ("BUY", "SELL"):
                action = "HOLD"
            pipeline_allowed = action in ("BUY", "SELL") and risk.allowed and quality.allowed

            filt = apply_profitability_filters(row.to_dict(), settings=settings)
            filter_passed = filt.passed
            if pipeline_allowed and not filter_passed:
                filter_blocks += 1

            allowed = pipeline_allowed and filter_passed

            ts = pd.to_datetime(row.get("timestamp", row.name), utc=True)
            bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(i, len(c) - 1))
            outcome = simulate_outcome(c, bar_idx, action if allowed else "HOLD")
            duration = _duration_bars(c, bar_idx, action) if allowed else 0

            records.append({
                "timestamp": ts.isoformat(),
                "year": int(ts.year),
                "month": int(ts.month),
                "weekday": int(ts.weekday()),
                "hour": int(ts.hour),
                "regime": regime,
                "engine": calibrated.decision.engine,
                "direction": action,
                "allowed": allowed,
                "pipeline_allowed": pipeline_allowed,
                "filter_passed": filter_passed,
                "filter_blocked_by": list(filt.blocked_by),
                "rsi": filt.rsi,
                "adx": filt.adx,
                "confidence": float(calibrated.final_confidence),
                "risk_percent": float(risk.risk_percent),
                "quality_score": float(quality.score),
                "r_multiple": float(outcome["r_multiple"]),
                "mfe": float(outcome["mfe"]),
                "mae": float(outcome["mae"]),
                "duration_bars": duration,
            })
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev

    return {
        "phase": "19C",
        "days": days,
        "stride": stride,
        "bars_evaluated": len(records),
        "filter_blocks": filter_blocks,
        "filter_settings": settings.to_dict(),
        "trend_engine": "trend_rf_v41",
        "range_engine": "phase9_9",
        "simulation_only": True,
        "order_send": False,
        "records": records,
    }
