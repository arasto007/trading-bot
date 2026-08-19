"""Phase 15I — production replay with engine contribution split."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.monitoring.statistics import latency_summary, percentile
from tradingbot.ml.research.phase15i.config import RANGE_ENGINE_ID, TREND_ENGINE_ID


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    end = candles.index.max()
    return candles[candles.index >= end - timedelta(days=days)]


def replay_with_contribution(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days_list: tuple[int, ...] = (180, 365),
    base_dir: str | None = None,
    stride: int = 15,
    warmup: int = 350,
    use_recovery: bool = True,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for days in days_list:
        from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack

        PipelineCache.reset()
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=use_recovery)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        window = _filter_days(candles, days)
        market = MarketKey(symbol, timeframe)

        counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
        range_trades = 0
        trend_trades = 0
        range_engine_trades = 0
        trend_engine_trades = 0
        latencies: list[float] = []

        for i in range(warmup, len(window), stride):
            full_idx = candles.index.get_loc(window.index[i])
            sl = candles.iloc[max(0, full_idx - warmup) : full_idx + 1]
            import time
            t0 = time.perf_counter()
            try:
                sig = adapter.generate_signal(market, sl.copy())
            except KernelFallbackError:
                counts["HOLD"] += 1
                latencies.append((time.perf_counter() - t0) * 1000)
                continue
            latencies.append((time.perf_counter() - t0) * 1000)
            u = adapter.last_unified_signal
            if u is not None and u.direction in ("BUY", "SELL"):
                counts[u.direction] = counts.get(u.direction, 0) + 1
                if u.regime == "RANGE":
                    range_trades += 1
                elif u.regime == "TREND":
                    trend_trades += 1
                if u.engine == RANGE_ENGINE_ID:
                    range_engine_trades += 1
                elif u.engine == TREND_ENGINE_ID:
                    trend_engine_trades += 1
            elif sig is None:
                counts["HOLD"] += 1
            else:
                counts[sig.direction.name] = counts.get(sig.direction.name, 0) + 1

        actionable = counts.get("BUY", 0) + counts.get("SELL", 0)
        total = sum(counts.values()) or 1
        warm = latencies[3:] if len(latencies) > 3 else latencies
        all_trades = max(actionable, 1)
        results[f"{days}d"] = {
            "bars_evaluated": total,
            "buy": counts.get("BUY", 0),
            "sell": counts.get("SELL", 0),
            "hold": counts.get("HOLD", 0),
            "actionable_signals": actionable,
            "range_trades": range_trades,
            "trend_trades": trend_trades,
            "range_engine_trades": range_engine_trades,
            "trend_engine_trades": trend_engine_trades,
            "range_contribution_pct": round(range_trades / all_trades, 4),
            "trend_contribution_pct": round(trend_trades / all_trades, 4),
            "acceptance_rate": round(actionable / total, 4),
            "latency": {
                **latency_summary(warm),
                "warm_p95_ms": round(percentile(warm, 0.95), 3) if warm else 0.0,
            },
            "use_range_recovery": use_recovery,
        }

    return {"windows": results, "primary_days": days_list[0] if days_list else 180}
