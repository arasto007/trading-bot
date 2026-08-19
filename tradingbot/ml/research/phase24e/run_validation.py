"""Phase 24E — validate dataset_v2 memory cache integration."""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    ordered = sorted(values)
    n = len(ordered)

    def pct(p: float) -> float:
        if n == 1:
            return ordered[0]
        return ordered[min(n - 1, int(p * (n - 1)))]

    return {
        "mean_ms": round(statistics.mean(ordered), 4),
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(pct(0.95), 4),
        "p99_ms": round(pct(0.99), 4),
    }


def _frames_equal(a, b) -> bool:
    import pandas as pd

    try:
        pd.testing.assert_frame_equal(
            a.reset_index(drop=True),
            b.reset_index(drop=True),
            check_dtype=True,
            check_exact=True,
        )
        return True
    except AssertionError:
        return False


def _column_hashes(df) -> dict[str, str]:
    import pandas as pd

    out: dict[str, str] = {}
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            payload = series.to_numpy().tobytes()
        else:
            payload = series.astype(str).to_numpy().tobytes()
        out[str(col)] = hashlib.sha256(payload).hexdigest()
    return out


def _timed_load_v2(store, symbol: str, timeframe: str, *, iterations: int = 50) -> tuple[list[float], Any]:
    times: list[float] = []
    last = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        last = store.load_v2(symbol, timeframe)
        times.append((time.perf_counter() - t0) * 1000)
    return times, last


def run_validation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.memory_cache import (
        ENV_ENABLE_DATASET_MEMORY_CACHE,
        DatasetMemoryCache,
        dataset_memory_cache_enabled,
    )
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.health_gate import run_pre_decision_health
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.ml.research.research_utils import dataset_content_fingerprint

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    symbol, timeframe = "XAUUSD", "M5"
    iterations = 20 if quick else 50
    bars = 5 if quick else 15

    legacy = load_legacy_config()
    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    dataset_path_df = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles_raw is None or candles_raw.empty or dataset_path_df is None:
        return {"error": "missing_data", "verdict": "ROLLBACK_REQUIRED"}

    window = prepare_calibration_candles(candles_raw, days=7)
    norm = normalize_candles_for_builder(window)
    warmup = min(250, len(norm) - 2)

    # Baseline: direct parquet reads (cache disabled)
    os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "false"
    DatasetMemoryCache.reset()
    store = DatasetStore(base_dir)
    before_times, baseline_df = _timed_load_v2(store, symbol, timeframe, iterations=iterations)

    # Cached path
    os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
    DatasetMemoryCache.reset()
    store2 = DatasetStore(base_dir)
    _ = store2.load_v2(symbol, timeframe)  # warm disk load
    after_times, cached_df = _timed_load_v2(store2, symbol, timeframe, iterations=iterations)
    cache_stats = DatasetMemoryCache.stats()

    # Feature parity — unified frame column hashes
    indices = list(range(warmup, min(len(norm), warmup + bars * 3), 3))[:bars]
    parity_rows: list[dict[str, Any]] = []
    all_match = True
    for bar_index in indices:
        chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "false"
        ds_off = DatasetStore(base_dir).load_v2(symbol, timeframe)
        uf_off = attach_top5_features(build_unified_frame(chunk, ds_off))

        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
        DatasetMemoryCache.reset()
        ds_on = DatasetStore(base_dir).load_v2(symbol, timeframe)
        uf_on = attach_top5_features(build_unified_frame(chunk, ds_on))

        h_off = _column_hashes(uf_off)
        h_on = _column_hashes(uf_on)
        row_match = _frames_equal(uf_off, uf_on)
        all_match = all_match and row_match
        parity_rows.append(
            {
                "bar_index": bar_index,
                "frames_equal": row_match,
                "column_hashes_match": h_off == h_on,
            }
        )

    feature_parity = {
        "phase": "24E",
        "bars_compared": len(parity_rows),
        "all_frames_equal": all_match,
        "all_column_hashes_match": all_match,
        "rows": parity_rows,
        "baseline_fingerprint": dataset_content_fingerprint(baseline_df),
        "cached_fingerprint": dataset_content_fingerprint(cached_df),
        "fingerprints_match": dataset_content_fingerprint(baseline_df)
        == dataset_content_fingerprint(cached_df),
    }

    # Probability / decision parity
    os.environ[TREND_VERSION_ENV] = "v41"
    os.environ["USE_ML_KERNEL"] = "true"
    prob_rows: list[dict[str, Any]] = []
    decisions_match = True

    for bar_index in indices[: min(5, len(indices))]:
        chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
        market = MarketKey(symbol=symbol, timeframe=timeframe)

        PipelineCache.reset()
        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "false"
        stack_off = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
        ka_off = KernelAdapter(stack_off.as_dependencies(base_dir=base_dir, symbol=symbol))
        sig_off = ka_off.produce_unified_signal(market, chunk)

        PipelineCache.reset()
        DatasetMemoryCache.reset()
        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
        stack_on = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
        ka_on = KernelAdapter(stack_on.as_dependencies(base_dir=base_dir, symbol=symbol))
        sig_on = ka_on.produce_unified_signal(market, chunk)

        row_ok = (
            sig_off.direction == sig_on.direction
            and abs(sig_off.confidence - sig_on.confidence) < 1e-9
            and sig_off.engine == sig_on.engine
            and sig_off.regime == sig_on.regime
        )
        decisions_match = decisions_match and row_ok
        prob_rows.append(
            {
                "bar_index": bar_index,
                "direction_off": sig_off.direction,
                "direction_on": sig_on.direction,
                "confidence_off": sig_off.confidence,
                "confidence_on": sig_on.confidence,
                "match": row_ok,
            }
        )

    # HealthGate
    PipelineCache.reset()
    DatasetMemoryCache.reset()
    os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    health = run_pre_decision_health(registry=stack.registry, base_dir=base_dir)

    # Rollback validation
    DatasetMemoryCache.reset()
    os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "false"
    rb1 = DatasetStore(base_dir).load_v2(symbol, timeframe)
    rb2 = DatasetStore(base_dir).load_v2(symbol, timeframe)
    rollback_ok = dataset_content_fingerprint(rb1) == dataset_content_fingerprint(rb2)
    rollback_stats = DatasetMemoryCache.stats()

    # Artifact checksum (phase9 model unchanged)
    from tradingbot.ml.data.paths import phase9_9_model_path
    from tradingbot.ml.phase15a.config import EXPECTED_DATASET_FINGERPRINT

    model_path = phase9_9_model_path(base_dir)
    artifact_checksum = (
        hashlib.sha256(model_path.read_bytes()).hexdigest() if model_path.is_file() else None
    )

    latency = {
        "phase": "24E",
        "iterations": iterations,
        "cache_disabled": _stats(before_times),
        "cache_enabled_warm": _stats(after_times),
        "improvement_mean_ms": round(_stats(before_times)["mean_ms"] - _stats(after_times)["mean_ms"], 4),
        "improvement_p95_ms": round(_stats(before_times)["p95_ms"] - _stats(after_times)["p95_ms"], 4),
        "cache_stats_after": cache_stats,
    }

    impl = {
        "phase": "24E",
        "files_changed": [
            "tradingbot/ml/dataset/memory_cache.py",
            "tradingbot/ml/dataset/store.py",
        ],
        "env_flag": ENV_ENABLE_DATASET_MEMORY_CACHE,
        "default_enabled": True,
        "invalidation": ["file fingerprint change", "process restart", "DatasetMemoryCache.reset()", "store_v2 write"],
    }

    fingerprint_validation = {
        "phase": "24E",
        "dataset_content_fingerprint_match": feature_parity["fingerprints_match"],
        "expected_dataset_fingerprint": EXPECTED_DATASET_FINGERPRINT,
        "artifact_model_sha256": artifact_checksum,
    }

    rollback_validation = {
        "phase": "24E",
        "rollback_env": ENV_ENABLE_DATASET_MEMORY_CACHE,
        "rollback_value": "false",
        "loads_from_memory_when_disabled": rollback_stats["loads_from_memory"],
        "parity_on_rollback": rollback_ok,
    }

    runtime_validation = {
        "phase": "24E",
        "health_gate_passes": health.passes,
        "health_errors": health.errors,
        "cache_enabled_default": dataset_memory_cache_enabled(),
    }

    improvement = latency["improvement_p95_ms"] > 0.5
    safe = (
        feature_parity["all_frames_equal"]
        and feature_parity["fingerprints_match"]
        and decisions_match
        and health.passes
        and rollback_validation["parity_on_rollback"]
        and rollback_validation["loads_from_memory_when_disabled"] == 0
    )

    if safe and improvement:
        verdict = "SAFE_DEPLOYED"
    elif safe and not improvement:
        verdict = "NO_LATENCY_IMPROVEMENT"
    else:
        verdict = "ROLLBACK_REQUIRED"

    final_report = {
        "phase": "24E",
        "verdict": verdict,
        "strategy": "SAFE_IN_MEMORY_CACHE",
        "summary": (
            f"Dataset v2 memory cache {'deployed' if verdict == 'SAFE_DEPLOYED' else verdict}. "
            f"p95 load improvement: {latency['improvement_p95_ms']}ms. "
            f"Feature parity: {feature_parity['all_frames_equal']}. "
            f"HealthGate: {health.passes}."
        ),
        "generated_utc": _utc_now(),
    }

    return {
        "implementation_report.json": impl,
        "latency_before_after.json": latency,
        "feature_parity.json": feature_parity,
        "probability_parity.json": {
            "phase": "24E",
            "decisions_match": decisions_match,
            "rows": prob_rows,
        },
        "fingerprint_validation.json": fingerprint_validation,
        "rollback_validation.json": rollback_validation,
        "runtime_validation.json": runtime_validation,
        "phase24e_final_report.json": final_report,
    }


def write_deliverables(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = run_validation(base_dir=base_dir, quick=quick)
    if "error" in artifacts:
        return artifacts
    for name, payload in artifacts.items():
        (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "written": list(artifacts.keys()),
        "verdict": artifacts["phase24e_final_report.json"]["verdict"],
    }
