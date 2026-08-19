"""Phase 18B — long-run stability (365d, stride 1 and 5)."""

from __future__ import annotations

import os
import time
import tracemalloc
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
from tradingbot.ml.monitoring.statistics import latency_summary


def _run_stride(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None,
    symbol: str,
    days: int,
    stride: int,
    warmup: int,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    unified_v41 = attach_top5_features(unified)

    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()
    try:
        registry = EngineRegistry.build_default(
            base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
        )
        trend = registry.get(TREND_ENGINE_V41_ID)
        range_eng = registry.get("phase9_9")
        if trend is None or range_eng is None:
            raise RuntimeError("engines_missing")

        latencies: list[float] = []
        probs: list[float] = []
        start = max(warmup, 0)
        t0_all = time.perf_counter()
        for i in range(start, len(unified), max(1, stride)):
            row = unified.iloc[i]
            row41 = unified_v41.iloc[i]
            regime = rule_classify_row(row)
            t0 = time.perf_counter()
            if regime == "RANGE":
                from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
                ev = range_eng.inner.evaluate(row=row_for_phase99_range(row))
                probs.append(float(ev.get("confidence", ev.get("probability", 0.0))))
            else:
                ev = trend.inner.evaluate(row41, regime="TREND" if regime == "TREND" else regime)
                probs.append(float(ev.get("probability", 0.0)))
            latencies.append((time.perf_counter() - t0) * 1000)

        # Prediction stability: re-run first 20 TREND bars, expect identical probs
        stable = True
        checked = 0
        for i in range(start, len(unified), max(1, stride)):
            if checked >= 20:
                break
            row41 = unified_v41.iloc[i]
            regime = rule_classify_row(unified.iloc[i])
            if regime != "TREND":
                continue
            p1 = float(trend.inner.evaluate(row41, regime="TREND").get("probability", 0.0))
            p2 = float(trend.inner.evaluate(row41, regime="TREND").get("probability", 0.0))
            if abs(p1 - p2) > 1e-12:
                stable = False
                break
            checked += 1

        # Cache behavior
        PipelineCache.reset()
        PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        cache_ok = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol) is not None

        wall_s = time.perf_counter() - t0_all
        warm = latencies[3:] if len(latencies) > 3 else latencies
        return {
            "stride": stride,
            "bars": len(latencies),
            "wall_seconds": round(wall_s, 3),
            "latency": latency_summary(warm),
            "prediction_stable": stable,
            "stability_checks": checked,
            "cache_ok": cache_ok,
            "prob_mean": round(float(np.mean(probs)), 6) if probs else 0.0,
            "prob_std": round(float(np.std(probs)), 6) if probs else 0.0,
        }
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev


def run_stability(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    days: int = 365,
    warmup: int = 350,
) -> dict[str, Any]:
    tracemalloc.start()
    mem_before = tracemalloc.get_traced_memory()[0]

    s5 = _run_stride(
        candles, dataset, base_dir=base_dir, symbol=symbol,
        days=days, stride=5, warmup=warmup,
    )
    s1 = _run_stride(
        candles, dataset, base_dir=base_dir, symbol=symbol,
        days=days, stride=1, warmup=warmup,
    )

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    mem_delta_mb = (peak - mem_before) / (1024 * 1024)

    # CPU proxy: wall time per bar
    cpu_proxy = {
        "stride5_ms_per_bar": round(s5["wall_seconds"] * 1000 / max(s5["bars"], 1), 3),
        "stride1_ms_per_bar": round(s1["wall_seconds"] * 1000 / max(s1["bars"], 1), 3),
    }

    passed = (
        s5["bars"] > 0
        and s1["bars"] > 0
        and s5["prediction_stable"]
        and s1["prediction_stable"]
        and s5["cache_ok"]
        and s1["cache_ok"]
        and mem_delta_mb < 512
    )

    return {
        "phase": "18B",
        "passed": passed,
        "days": days,
        "stride_5": s5,
        "stride_1": s1,
        "memory": {
            "peak_delta_mb": round(mem_delta_mb, 3),
            "current_mb": round(current / (1024 * 1024), 3),
            "peak_mb": round(peak / (1024 * 1024), 3),
        },
        "cpu_proxy": cpu_proxy,
        "prediction_stability": s5["prediction_stable"] and s1["prediction_stable"],
        "cache_behavior_ok": s5["cache_ok"] and s1["cache_ok"],
    }
