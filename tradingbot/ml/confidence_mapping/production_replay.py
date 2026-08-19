"""Phase 15H — production replay with mapped confidence."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.monitoring.statistics import latency_summary, percentile


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    end = candles.index.max()
    return candles[candles.index >= end - timedelta(days=days)]


def replay_mapped_production(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days_list: tuple[int, ...] = (180, 365),
    base_dir: str | None = None,
    stride: int = 10,
    warmup: int = 350,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for days in days_list:
        from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

        PipelineCache.reset()
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        window = _filter_days(candles, days)
        market = MarketKey(symbol, timeframe)

        counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
        confidences: list[float] = []
        latencies: list[float] = []
        timeouts = 0

        for i in range(warmup, len(window), stride):
            full_idx = candles.index.get_loc(window.index[i])
            sl = candles.iloc[max(0, full_idx - warmup) : full_idx + 1]
            import time
            t0 = time.perf_counter()
            try:
                sig = adapter.generate_signal(market, sl.copy())
            except KernelFallbackError:
                timeouts += 1
                counts["HOLD"] += 1
                latencies.append((time.perf_counter() - t0) * 1000)
                continue
            latencies.append((time.perf_counter() - t0) * 1000)
            u = adapter.last_unified_signal
            if u is not None:
                confidences.append(float(u.confidence))
                counts[u.direction] = counts.get(u.direction, 0) + 1
            elif sig is None:
                counts["HOLD"] += 1
            else:
                counts[sig.direction.name] = counts.get(sig.direction.name, 0) + 1

        actionable = counts.get("BUY", 0) + counts.get("SELL", 0)
        total = sum(counts.values()) or 1
        warm = latencies[3:] if len(latencies) > 3 else latencies
        results[f"{days}d"] = {
            "bars_evaluated": total,
            "buy": counts.get("BUY", 0),
            "sell": counts.get("SELL", 0),
            "hold": counts.get("HOLD", 0),
            "actionable_signals": actionable,
            "acceptance_rate": round(actionable / total, 4),
            "confidence_histogram": {
                "mean": round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
                "min": round(min(confidences), 4) if confidences else 0.0,
                "max": round(max(confidences), 4) if confidences else 0.0,
                "p50": round(percentile(confidences, 0.5), 4) if confidences else 0.0,
            },
            "latency": {
                **latency_summary(warm),
                "warm_p95_ms": round(percentile(warm, 0.95), 3) if warm else 0.0,
            },
            "pipeline_timeouts": timeouts,
            "uses_confidence_mapper": True,
        }

    return {"windows": results, "primary_days": days_list[0] if days_list else 180}
