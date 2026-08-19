"""Phase 18A — parallel v40/v41 shadow runner (no execution)."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.phase18a.comparator import ShadowComparator
from tradingbot.ml.research.phase18a.config import DEFAULT_WARMUP, RF_THRESHOLD
from tradingbot.ml.research.phase18a.equity import ShadowEquityCurve
from tradingbot.ml.research.phase18a.latency import LatencyProfiler
from tradingbot.ml.research.phase18a.safety import ORDER_SEND_CALLS, assert_no_execution
from tradingbot.ml.research.phase18a.trade_logger import ShadowTradeLogger
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _ts(row: pd.Series) -> str:
    if "timestamp" in row.index:
        return str(row["timestamp"])
    return str(row.name)


def _proxy_return(signal: str, probability: float, regime: str) -> float | None:
    if signal not in ("BUY", "SELL"):
        return None
    if regime == "TREND":
        return float(probability) - RF_THRESHOLD
    # RANGE: fixed small proxy for actionable phase9_9
    return 0.01


def run_shadow_comparison(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 365,
    stride: int = 5,
    warmup: int = DEFAULT_WARMUP,
) -> dict[str, Any]:
    """
    For each bar:
      Regime Router →
        TREND → v40 + v41 engines in parallel
        RANGE → phase9_9 (identical for both paths)
      → ShadowComparator → TradeLogger → Equity → Latency

    Never calls order_send / execution.
    """
    assert_no_execution()

    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    unified_v41 = attach_top5_features(unified)

    PipelineCache.reset()
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_eng = registry.get("phase9_9")
    trend_v40_wrap = registry.get(TREND_ENGINE_ID)
    trend_v41_wrap = registry.get(TREND_ENGINE_V41_ID)
    if range_eng is None or trend_v40_wrap is None or trend_v41_wrap is None:
        raise RuntimeError("phase18a_engines_missing")

    range_inner = range_eng.inner
    trend_v40 = trend_v40_wrap.inner
    trend_v41 = trend_v41_wrap.inner

    comparator = ShadowComparator()
    logger = ShadowTradeLogger()
    equity_v40 = ShadowEquityCurve(label="trend_rf_v40")
    equity_v41 = ShadowEquityCurve(label="trend_rf_v41")
    latency = LatencyProfiler()

    regime_counts = {"TREND": 0, "RANGE": 0, "OTHER": 0}
    range_signal_mismatch = 0
    errors: list[str] = []

    start = max(warmup, 0)
    for i in range(start, len(unified), max(1, stride)):
        row = unified.iloc[i]
        row_v41 = unified_v41.iloc[i]
        regime = rule_classify_row(row)
        key = regime if regime in ("TREND", "RANGE") else "OTHER"
        regime_counts[key] = regime_counts.get(key, 0) + 1
        ts = _ts(row)

        t_total = time.perf_counter()
        try:
            if regime == "RANGE":
                t0 = time.perf_counter()
                from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
                r40 = range_inner.evaluate(row=row_for_phase99_range(row))
                lat40 = (time.perf_counter() - t0) * 1000
                t1 = time.perf_counter()
                r41 = range_inner.evaluate(row=row_for_phase99_range(row_v41))
                lat41 = (time.perf_counter() - t1) * 1000
                # Normalize engine tags for RANGE path
                r40 = {**r40, "engine": "phase9_9", "probability": float(r40.get("confidence", r40.get("probability", 0.0)))}
                r41 = {**r41, "engine": "phase9_9", "probability": float(r41.get("confidence", r41.get("probability", 0.0)))}
                if str(r40.get("signal")) != str(r41.get("signal")):
                    range_signal_mismatch += 1
            else:
                # TREND (or OTHER treated as TREND path for engines)
                t0 = time.perf_counter()
                r40 = trend_v40.evaluate(row, regime="TREND" if regime == "TREND" else regime)
                lat40 = (time.perf_counter() - t0) * 1000
                t1 = time.perf_counter()
                r41 = trend_v41.evaluate(row_v41, regime="TREND" if regime == "TREND" else regime)
                lat41 = (time.perf_counter() - t1) * 1000
        except Exception as exc:  # noqa: BLE001 — capture for report, do not crash phase silently
            errors.append(f"bar={i}: {exc}")
            continue

        total_ms = (time.perf_counter() - t_total) * 1000
        latency.add(lat40, lat41, total_ms)

        cmp_row = comparator.compare(
            bar_index=i,
            timestamp=ts,
            regime=regime,
            v40=r40,
            v41=r41,
            latency_v40_ms=lat40,
            latency_v41_ms=lat41,
        )

        logger.log({
            **cmp_row,
            "symbol": symbol,
            "timeframe": timeframe,
            "stride": stride,
        })

        ret40 = _proxy_return(str(r40.get("signal")), float(r40.get("probability", 0.0)), regime)
        ret41 = _proxy_return(str(r41.get("signal")), float(r41.get("probability", 0.0)), regime)
        if ret40 is not None:
            equity_v40.add(ret40, timestamp=ts, regime=regime)
        if ret41 is not None:
            equity_v41.add(ret41, timestamp=ts, regime=regime)

    assert_no_execution()

    return {
        "phase": "18A",
        "days": days,
        "stride": stride,
        "bars_evaluated": comparator.agree + comparator.diverge,
        "regime_counts": regime_counts,
        "range_signal_mismatch": range_signal_mismatch,
        "range_identical": range_signal_mismatch == 0,
        "errors": errors,
        "runtime_crashes": len(errors),
        "order_send_calls": ORDER_SEND_CALLS,
        "comparator": comparator,
        "logger": logger,
        "equity_v40": equity_v40,
        "equity_v41": equity_v41,
        "latency": latency,
    }
