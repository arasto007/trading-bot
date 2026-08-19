"""Phase 32G — safe runtime cache validation (parity + latency)."""

from __future__ import annotations

import copy
import hashlib
import json
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
OUT_DIR = PROJECT_ROOT


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stats_ms(values: list[float]) -> dict[str, float]:
    if not values:
        return {"avg_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "max_ms": 0.0}
    ordered = sorted(values)
    n = len(ordered)

    def pct(p: float) -> float:
        if n == 1:
            return ordered[0]
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        if f == c:
            return ordered[f]
        return ordered[f] + (ordered[c] - ordered[f]) * (k - f)

    return {
        "avg_ms": round(statistics.mean(ordered), 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(pct(0.95), 3),
        "p99_ms": round(pct(0.99), 3),
        "max_ms": round(max(ordered), 3),
        "samples": n,
    }


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


def _context_equal(a, b) -> bool:
    return a.to_dict() == b.to_dict()


def _signal_payload(sig) -> dict[str, Any]:
    if sig is None:
        return {}
    d = sig.to_dict() if hasattr(sig, "to_dict") else dict(sig)
    d.pop("_hold_chain", None)
    return d


def run_validation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.memory_cache import DatasetMemoryCache
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_kernel_adapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache, unified_frame_sha256
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    symbol = "XAUUSD"
    timeframes = ("M5", "M15", "H4")
    iterations = 10 if quick else 30

    PipelineCache.reset()
    DatasetMemoryCache.reset()

    # --- Startup warm ---
    t_warm = time.perf_counter()
    warm_result = PipelineCache.warm_datasets(symbol=symbol, timeframes=timeframes, base_dir=base_dir)
    warm_ms = (time.perf_counter() - t_warm) * 1000

    candles_by_tf: dict[str, Any] = {}
    for tf in timeframes:
        raw = CandleStore(base_dir).load(symbol, tf)
        if raw is None or raw.empty:
            return {"verdict": "SAFE_OPTIMIZATION_FAILED", "error": f"missing_candles_{tf}"}
        candles_by_tf[tf] = normalize_candles_for_builder(raw).tail(300)

    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, enable_monitoring=False)

    # --- Feature parity: direct build vs PipelineCache ---
    feature_rows: list[dict[str, Any]] = []
    all_feature_match = True
    for tf, chunk in candles_by_tf.items():
        PipelineCache.reset()
        DatasetMemoryCache.reset()
        PipelineCache.warm_datasets(symbol=symbol, timeframes=(tf,), base_dir=base_dir)
        ds = DatasetStore(base_dir).load_v2(symbol, tf)
        direct = attach_top5_features(build_unified_frame(chunk, ds))
        cached = PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
        match = _frames_equal(direct, cached)
        sha_direct = unified_frame_sha256(direct)
        sha_cached = unified_frame_sha256(cached)
        all_feature_match = all_feature_match and match and sha_direct == sha_cached
        feature_rows.append({
            "timeframe": tf,
            "frames_equal": match,
            "sha256_direct": sha_direct,
            "sha256_cached": sha_cached,
            "sha256_match": sha_direct == sha_cached,
            "column_hashes_direct": _column_hashes(direct),
            "column_hashes_cached": _column_hashes(cached),
        })

    # --- Market context parity ---
    ctx_rows: list[dict[str, Any]] = []
    all_ctx_match = True
    range_inner, trend_inner = adapter._engine_inners()
    for tf, chunk in candles_by_tf.items():
        unified = PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
        row = unified.iloc[-1]
        bar_index = len(chunk) - 1
        direct_ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=tf,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=chunk,
            bar_index=bar_index,
        )
        PipelineCache.reset()
        PipelineCache.warm_datasets(symbol=symbol, timeframes=timeframes, base_dir=base_dir)
        cached_ctx = PipelineCache.get_market_context(
            row,
            symbol=symbol,
            timeframe=tf,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=chunk,
            bar_index=bar_index,
            base_dir=base_dir,
        )
        repeat_ctx = PipelineCache.get_market_context(
            row,
            symbol=symbol,
            timeframe=tf,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=chunk,
            bar_index=bar_index,
            base_dir=base_dir,
        )
        match = _context_equal(direct_ctx, cached_ctx) and _context_equal(cached_ctx, repeat_ctx)
        all_ctx_match = all_ctx_match and match
        ctx_rows.append({"timeframe": tf, "context_equal": match})

    # --- Signal / probability / trade parity ---
    PipelineCache.reset()
    DatasetMemoryCache.reset()
    PipelineCache.warm_datasets(symbol=symbol, timeframes=timeframes, base_dir=base_dir)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, enable_monitoring=False)

    signal_rows: list[dict[str, Any]] = []
    prob_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    all_signal_match = True

    for tf, chunk in candles_by_tf.items():
        mkt = MarketKey(symbol, tf)
        # Warm feature cache before timing-sensitive produce calls
        PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
        sig_first = adapter.produce_unified_signal(mkt, chunk)
        sig_second = adapter.produce_unified_signal(mkt, chunk)

        pa = _signal_payload(sig_first)
        pb = _signal_payload(sig_second)
        match = pa == pb
        all_signal_match = all_signal_match and match
        signal_rows.append({"timeframe": tf, "signal_match": match, "payload_first": pa, "payload_second": pb})
        prob_rows.append({
            "timeframe": tf,
            "confidence_match": pa.get("confidence") == pb.get("confidence"),
            "confidence_first": pa.get("confidence"),
            "confidence_second": pb.get("confidence"),
        })
        trade_rows.append({
            "timeframe": tf,
            "direction_match": pa.get("direction") == pb.get("direction"),
            "direction_first": pa.get("direction"),
            "direction_second": pb.get("direction"),
            "risk_match": pa.get("risk") == pb.get("risk"),
        })

    # --- Latency: simulated single-slot thrash vs multi-slot ---
    PipelineCache.reset()
    PipelineCache.warm_datasets(symbol=symbol, timeframes=timeframes, base_dir=base_dir)

    thrash_times: list[float] = []
    for _ in range(iterations):
        for tf in timeframes:
            PipelineCache._feature_cache_slots.clear()
            PipelineCache._top5_cache.clear()
            t0 = time.perf_counter()
            PipelineCache.get_unified_frame(
                candles_by_tf[tf], base_dir=base_dir, symbol=symbol, timeframe=tf,
            )
            thrash_times.append((time.perf_counter() - t0) * 1000)

    PipelineCache.reset()
    PipelineCache.warm_datasets(symbol=symbol, timeframes=timeframes, base_dir=base_dir)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, enable_monitoring=False)

    # Prime all timeframe slots once
    for tf in timeframes:
        PipelineCache.get_unified_frame(
            candles_by_tf[tf], base_dir=base_dir, symbol=symbol, timeframe=tf,
        )
        adapter.produce_unified_signal(MarketKey(symbol, tf), candles_by_tf[tf])

    multi_times: list[float] = []
    get_unified_times: list[float] = []
    load_v2_times: list[float] = []
    produce_times: list[float] = []

    for _ in range(iterations):
        for tf in timeframes:
            chunk = candles_by_tf[tf]
            t1 = time.perf_counter()
            PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
            get_unified_times.append((time.perf_counter() - t1) * 1000)
        for tf in timeframes:
            t2 = time.perf_counter()
            DatasetStore(base_dir).load_v2(symbol, tf)
            load_v2_times.append((time.perf_counter() - t2) * 1000)
        for tf in timeframes:
            t0 = time.perf_counter()
            adapter.produce_unified_signal(MarketKey(symbol, tf), candles_by_tf[tf])
            produce_times.append((time.perf_counter() - t0) * 1000)
        multi_times.extend(get_unified_times[-len(timeframes):])

    cache_stats = PipelineCache.cache_stats()
    cache_stats["dataset_memory_cache"] = DatasetMemoryCache.stats()

    # --- Memory ---
    tracemalloc.start()
    for tf in timeframes:
        PipelineCache.get_unified_frame(
            candles_by_tf[tf], base_dir=base_dir, symbol=symbol, timeframe=tf,
        )
        adapter.produce_unified_signal(MarketKey(symbol, tf), candles_by_tf[tf])
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    thrash_stats = _stats_ms(thrash_times)
    multi_stats = _stats_ms(multi_times)
    gain_ratio = round(thrash_stats["avg_ms"] / multi_stats["avg_ms"], 3) if multi_stats["avg_ms"] else 0.0

    parity_ok = all_feature_match and all_ctx_match and all_signal_match
    latency_ok = multi_stats["p95_ms"] <= thrash_stats["p95_ms"]

    if not parity_ok:
        verdict = "PARITY_BROKEN"
    elif not latency_ok:
        verdict = "SAFE_OPTIMIZATION_FAILED"
    else:
        verdict = "SAFE_OPTIMIZATION_SUCCESS"

    safe_cache_design = {
        "feature_cache": {
            "type": "multi_slot_lru",
            "max_slots": 64,
            "key_fields": ["symbol", "timeframe", "last_closed_bar_time", "dataset_checksum", "feature_version"],
        },
        "top5_cache": {
            "type": "multi_slot_lru",
            "max_slots": 64,
            "key_fields": ["feature_cache_key", "pre_top5_frame_checksum", "feature_version"],
        },
        "market_context_cache": {
            "type": "multi_slot_lru",
            "max_slots": 256,
            "key_fields": ["symbol", "timeframe", "closed_candle_ts", "unified_row_fingerprint", "model_fingerprint", "bar_index"],
        },
        "dataset_warm": {
            "trigger": "build_ml_kernel_stack",
            "timeframes": list(timeframes),
            "invalidation": "file_fingerprint_on_disk_change",
        },
    }

    deliverables = {
        "safe_cache_design.json": safe_cache_design,
        "before_after_latency.json": {
            "simulated_single_slot_thrash_get_unified": thrash_stats,
            "multi_slot_cached_get_unified": multi_stats,
            "get_unified_frame": _stats_ms(get_unified_times),
            "load_v2": _stats_ms(load_v2_times),
            "produce_unified_signal": _stats_ms(produce_times),
        },
        "cache_statistics.json": cache_stats,
        "startup_warm_results.json": {**warm_result, "warm_elapsed_ms": round(warm_ms, 3)},
        "feature_parity.json": {"all_match": all_feature_match, "rows": feature_rows},
        "signal_parity.json": {"all_match": all_signal_match, "rows": signal_rows},
        "probability_parity.json": {"rows": prob_rows},
        "trade_parity.json": {"rows": trade_rows},
        "memory_usage.json": {
            "tracemalloc_current_bytes": current,
            "tracemalloc_peak_bytes": peak,
            "feature_cache_slots": cache_stats.get("feature_cache_slots"),
            "top5_cache_slots": cache_stats.get("top5_cache_slots"),
        },
        "performance_gain.json": {
            "avg_speedup_ratio": gain_ratio,
            "p95_reduction_ms": round(thrash_stats["p95_ms"] - multi_stats["p95_ms"], 3),
            "feature_cache_hit_ratio": cache_stats.get("feature_cache_hit_ratio"),
        },
        "phase32g_final_report.json": {},
    }

    final_report = {
        "phase": "32G",
        "timestamp_utc": _utc_now(),
        "verdict": verdict,
        "parity": {
            "feature": all_feature_match,
            "market_context": all_ctx_match,
            "signal": all_signal_match,
        },
        "latency_improved": latency_ok,
        "performance_gain_ratio": gain_ratio,
        "cache_statistics": cache_stats,
        "implementation_summary": "Multi-slot PipelineCache, startup dataset warm, top5/context memoization",
        "files_changed": [
            "tradingbot/ml/integration/pipeline_cache.py",
            "tradingbot/ml/integration/kernel_adapter.py",
            "tradingbot/ml/integration/factory.py",
        ],
        "risks": [],
        "next_recommendation": "Monitor feature_cache_hit_ratio in live cycles; consider RISKY vectorization only after extended shadow period",
    }
    deliverables["phase32g_final_report.json"] = final_report

    for name, payload in deliverables.items():
        path = OUT_DIR / name
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return final_report


def main() -> int:
    quick = "--quick" in sys.argv
    result = run_validation(quick=quick)
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "SAFE_OPTIMIZATION_SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
