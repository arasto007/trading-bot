"""Phase 15B — kernel replay validation (180-day, no execution)."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.health_gate import run_pre_decision_health
from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
from tradingbot.ml.integration.monitoring import write_pipeline_statistics
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.signal_mapper import trading_signal_schema
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum


@dataclass
class ReplayStats:
    bars_evaluated: int = 0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    fallback_count: int = 0
    ml_signals: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        lats = self.latencies_ms
        return {
            "bars_evaluated": self.bars_evaluated,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "hold_count": self.hold_count,
            "fallback_count": self.fallback_count,
            "ml_signals": self.ml_signals,
            "latency": {
                "mean_ms": round(statistics.mean(lats), 3) if lats else 0.0,
                "max_ms": round(max(lats), 3) if lats else 0.0,
                "p50_ms": round(statistics.median(lats), 3) if lats else 0.0,
                "under_30ms_rate": round(sum(1 for x in lats if x < 30) / len(lats), 4) if lats else 0.0,
                "under_50ms_rate": round(sum(1 for x in lats if x < 50) / len(lats), 4) if lats else 0.0,
            },
            "errors": self.errors[:20],
        }


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    end = candles.index.max()
    start = end - timedelta(days=days)
    return candles[candles.index >= start]


def run_kernel_replay(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    base_dir: str | None = None,
    stride: int = 5,
    warmup: int = 120,
) -> dict[str, Any]:
    """Replay kernel ML signal path over historical candles — no execution."""
    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    registry = MLKernelRegistry(
        {"BASE_DIR": base_dir or "."},
        adapter=adapter,
        base_dir=base_dir,
    )

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        return {"passes": False, "error": "candles_unavailable"}

    window = _filter_days(candles, days)
    stats = ReplayStats()
    checksum_stable = True
    first_chk = validate_trend_checksum(base_dir=base_dir)

    market = MarketKey(symbol, timeframe)
    # Pre-warm feature cache and prediction path before latency measurement.
    if len(window) > warmup:
        registry.generate_signal(market, window.iloc[: warmup + 1])

    indices = range(warmup, len(window), stride)

    for i in indices:
        slice_df = window.iloc[max(0, i - warmup) : i + 1]
        stats.bars_evaluated += 1
        t0 = time.perf_counter()
        try:
            signal = registry.generate_signal(market, slice_df)
            elapsed = (time.perf_counter() - t0) * 1000
            stats.latencies_ms.append(elapsed)
            if registry.last_source == "legacy_fallback":
                stats.fallback_count += 1
            elif signal is not None:
                stats.ml_signals += 1
                if signal.direction.name == "BUY":
                    stats.buy_count += 1
                elif signal.direction.name == "SELL":
                    stats.sell_count += 1
            else:
                stats.hold_count += 1
        except Exception as exc:
            stats.errors.append(str(exc))
            stats.fallback_count += 1

    last_chk = validate_trend_checksum(base_dir=base_dir)
    checksum_stable = (
        first_chk.get("valid") == last_chk.get("valid")
        and first_chk.get("bundle_sha256") == last_chk.get("bundle_sha256")
    )

    health = run_pre_decision_health(registry=stack.registry, base_dir=base_dir)
    lat = stats.to_dict()["latency"]
    warm = stats.latencies_ms[3:] if len(stats.latencies_ms) > 3 else stats.latencies_ms
    warm_mean = statistics.mean(warm) if warm else 0.0
    warm_max = max(warm) if warm else 0.0
    warm_sorted = sorted(warm)
    p95 = warm_sorted[int(len(warm_sorted) * 0.95)] if warm_sorted else 0.0
    lat["warm_mean_ms"] = round(warm_mean, 3)
    lat["warm_max_ms"] = round(warm_max, 3)
    lat["warm_p95_ms"] = round(p95, 3)
    stats_dict = stats.to_dict()
    stats_dict["latency"] = lat

    passes = (
        health.passes
        and checksum_stable
        and warm_mean < 30.0
        and p95 < 50.0
        and lat.get("under_50ms_rate", 0) >= 0.95
        and stats.bars_evaluated > 0
    )

    payload = {
        "phase": "15B",
        "passes": passes,
        "stats": stats_dict,
        "registry_stats": registry.stats(),
        "health": health.to_dict(),
        "checksum_stable": checksum_stable,
        "signal_mapping_schema": trading_signal_schema(),
    }
    write_pipeline_statistics(payload, base_dir=base_dir)
    return payload
