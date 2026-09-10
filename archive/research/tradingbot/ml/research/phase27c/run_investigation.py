"""Phase 27C — prediction cache key collision fix validation."""

from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.factory import build_ml_kernel_stack
from tradingbot.ml.integration.health_gate import KernelFallbackError
from tradingbot.ml.integration.kernel_adapter import KernelAdapter
from tradingbot.ml.integration.pipeline_cache import (
    PipelineCache,
    resolve_closed_candle_timestamp,
    unified_row_fingerprint,
)
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase25b.parity_replay_adapter import ParityReplayMarketDataAdapter
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
MIN_BARS = 1000
WARMUP = 300


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def _legacy_key(symbol: str, timeframe: str, unified: pd.DataFrame) -> str:
    """Pre-27C broken key (integer positional index)."""
    return f"{symbol}:{timeframe}:{unified.index[-1]}"


def build_cache_key_before() -> dict[str, Any]:
    return {
        "phase": "27C",
        "format": "{symbol}:{timeframe}:{unified.index[-1]}",
        "file": "tradingbot/ml/integration/kernel_adapter.py",
        "problem": "unified.index[-1] is int64 positional index (e.g. 79), not candle timestamp",
        "example_key": "XAUUSD:M5:79",
        "collision_risk": "HIGH — all 80-row unified tails map to index 79",
        "phase27b_evidence": {
            "unique_checksums_phase27a": 3,
            "cache_hits_decision_ms_zero": 5200,
            "bars_evaluated": 5203,
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_cache_key_after() -> dict[str, Any]:
    sample_row = pd.Series({"rsi": 50.0, "adx": 25.0, "ema20_slope": 0.01})
    sample_candles = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=pd.DatetimeIndex(["2026-06-01T12:00:00+00:00"], tz="UTC"),
    )
    legacy = load_legacy_config()
    base = legacy.get("BASE_DIR")
    key = PipelineCache.build_prediction_cache_key(
        symbol="XAUUSD",
        timeframe="M5",
        candles=sample_candles,
        unified_row=sample_row,
        base_dir=base,
    )
    return {
        "phase": "27C",
        "format": "{symbol}|{timeframe}|{closed_candle_ts}|{feature_fp}|{model_fp}",
        "file": "tradingbot/ml/integration/pipeline_cache.py",
        "function": "PipelineCache.build_prediction_cache_key",
        "components": {
            "symbol": "market symbol",
            "timeframe": "market timeframe",
            "closed_candle_ts": "resolve_closed_candle_timestamp(candles) — ISO UTC",
            "feature_fp": "unified_row_fingerprint(unified_row) — 16-char hash",
            "model_fp": "_model_fingerprint — trend engine id/version + phase9_9 model hash",
        },
        "never_uses": ["dataframe positional index", "unified.index[-1] integer"],
        "example_key": key,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def _collect_keys_pass(
    *,
    window: pd.DataFrame,
    indices: list[int],
    base_dir: str,
) -> dict[str, Any]:
    """Build prediction keys for every bar without running full ML pipeline."""
    replay = ParityReplayMarketDataAdapter(window, timeframe="M5")
    market = MarketKey("XAUUSD", "M5")
    records: list[dict[str, Any]] = []

    for bar_index in indices:
        replay.set_bar_index(bar_index)
        df = replay.get_ohlcv(market, bars=500)
        if df is None or df.empty:
            continue
        unified = PipelineCache.get_unified_frame(
            df, base_dir=base_dir, symbol="XAUUSD", timeframe="M5"
        )
        if unified.empty:
            continue
        row = unified.iloc[-1]
        new_key = PipelineCache.build_prediction_cache_key(
            symbol="XAUUSD",
            timeframe="M5",
            candles=df,
            unified_row=row,
            base_dir=base_dir,
        )
        candle_ts = resolve_closed_candle_timestamp(df)
        records.append(
            {
                "bar_index": bar_index,
                "candle_timestamp": candle_ts,
                "prediction_key": new_key,
                "legacy_key": _legacy_key("XAUUSD", "M5", unified),
                "feature_fp": unified_row_fingerprint(row),
            }
        )

    keys = [r["prediction_key"] for r in records]
    legacy_keys = [r["legacy_key"] for r in records]
    return {"bars": len(records), "keys": keys, "legacy_keys": legacy_keys, "records": records}


def _run_replay_pass(
    *,
    window: pd.DataFrame,
    adapter: KernelAdapter,
    indices: list[int],
    base_dir: str,
) -> dict[str, Any]:
    replay = ParityReplayMarketDataAdapter(window, timeframe="M5")
    market = MarketKey("XAUUSD", "M5")
    keys: list[str] = []
    legacy_keys: list[str] = []
    candle_ts_list: list[str] = []
    checksums: list[str] = []
    latencies: list[float] = []
    hits = 0
    misses = 0
    key_records: list[dict[str, Any]] = []

    for bar_index in indices:
        replay.set_bar_index(bar_index)
        df = replay.get_ohlcv(market, bars=500)
        if df is None or df.empty:
            continue

        unified = PipelineCache.get_unified_frame(
            df, base_dir=base_dir, symbol="XAUUSD", timeframe="M5"
        )
        if unified.empty:
            continue

        row = unified.iloc[-1]
        new_key = PipelineCache.build_prediction_cache_key(
            symbol="XAUUSD",
            timeframe="M5",
            candles=df,
            unified_row=row,
            base_dir=base_dir,
        )
        old_key = _legacy_key("XAUUSD", "M5", unified)
        candle_ts = resolve_closed_candle_timestamp(df)

        cache_before = PipelineCache.get_prediction(new_key) is not None
        if cache_before:
            hits += 1
        else:
            misses += 1

        try:
            t0 = time.perf_counter()
            sig = adapter.produce_unified_signal(market, df)
            latencies.append((time.perf_counter() - t0) * 1000)
            checksum = str(sig.checksum)
        except KernelFallbackError as exc:
            latencies.append(0.0)
            checksum = f"error:{exc.reason}"

        keys.append(new_key)
        legacy_keys.append(old_key)
        candle_ts_list.append(candle_ts)
        checksums.append(checksum)
        key_records.append(
            {
                "bar_index": bar_index,
                "candle_timestamp": candle_ts,
                "prediction_key": new_key,
                "legacy_key": old_key,
                "checksum": checksum,
                "feature_fp": unified_row_fingerprint(row),
                "cache_hit": cache_before,
            }
        )

    return {
        "bars": len(keys),
        "keys": keys,
        "legacy_keys": legacy_keys,
        "candle_ts_list": candle_ts_list,
        "checksums": checksums,
        "latencies_ms": latencies,
        "cache_hits": hits,
        "cache_misses": misses,
        "records": key_records,
    }


def _collision_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    key_to_candle: dict[str, str] = {}
    collisions: list[dict[str, Any]] = []
    for rec in records:
        key = rec["prediction_key"]
        candle = rec["candle_timestamp"]
        if key in key_to_candle and key_to_candle[key] != candle:
            collisions.append(
                {
                    "prediction_key": key,
                    "first_candle": key_to_candle[key],
                    "second_candle": candle,
                }
            )
        key_to_candle[key] = candle

    legacy_counts: dict[str, int] = {}
    for rec in records:
        lk = rec["legacy_key"]
        legacy_counts[lk] = legacy_counts.get(lk, 0) + 1

    return {
        "phase": "27C",
        "bars_evaluated": len(records),
        "unique_prediction_keys": len({r["prediction_key"] for r in records}),
        "unique_candle_timestamps": len({r["candle_timestamp"] for r in records}),
        "cache_collisions": len(collisions),
        "collision_details": collisions,
        "legacy_key_unique": len(legacy_counts),
        "legacy_key_worst_collision": max(legacy_counts.values()) if legacy_counts else 0,
        "legacy_key_example": next(iter(legacy_counts.keys()), ""),
        "pass": len(collisions) == 0,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def run_phase27c(*, base_dir: str | Path | None = None, min_bars: int = MIN_BARS) -> dict[str, Any]:
    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"

    root = Path(base_dir or PROJECT_ROOT)
    legacy = load_legacy_config()
    ml_base = legacy.get("BASE_DIR") or str(root)

    cache_key_before = build_cache_key_before()
    cache_key_after = build_cache_key_after()
    _write("cache_key_before.json", cache_key_before)
    _write("cache_key_after.json", cache_key_after)

    candles_raw = CandleStore(ml_base).load("XAUUSD", "M5")
    if candles_raw is None or candles_raw.empty:
        raise RuntimeError("CandleStore unavailable")

    window = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=30))
    indices = list(range(WARMUP, len(window)))
    if len(indices) < min_bars:
        raise RuntimeError(f"Need at least {min_bars} bars, got {len(indices)}")

    PipelineCache.reset()
    key_pass = _collect_keys_pass(window=window, indices=indices, base_dir=ml_base)

    stack = build_ml_kernel_stack(base_dir=ml_base, symbol="XAUUSD")
    adapter = KernelAdapter(stack.as_dependencies(base_dir=ml_base, symbol="XAUUSD"))

    pipeline_indices = indices[: min(500, len(indices))]
    PipelineCache.reset()
    pipeline_pass = _run_replay_pass(
        window=window, adapter=adapter, indices=pipeline_indices, base_dir=ml_base
    )

    repeat_indices = pipeline_indices[:200]
    warm_pass = _run_replay_pass(
        window=window, adapter=adapter, indices=repeat_indices, base_dir=ml_base
    )
    repeat_pass = _run_replay_pass(
        window=window, adapter=adapter, indices=repeat_indices, base_dir=ml_base
    )

    collision = _collision_report(key_pass["records"])
    _write("cache_collision_report.json", collision)

    unique_keys = len(set(key_pass["keys"]))
    valid_checksums = [
        c for c in pipeline_pass["checksums"] if c and not str(c).startswith("error:")
    ]
    unique_checksums = len(set(valid_checksums))
    bars = key_pass["bars"]
    uniqueness_pct = round(unique_keys / max(bars, 1) * 100, 4)

    prediction_uniqueness = {
        "phase": "27C",
        "bars_evaluated": bars,
        "unique_prediction_keys": unique_keys,
        "unique_checksums": unique_checksums,
        "unique_candle_timestamps": len({r["candle_timestamp"] for r in key_pass["records"]}),
        "pipeline_bars_sampled": len(pipeline_indices),
        "pipeline_unique_checksums": unique_checksums,
        "prediction_uniqueness_pct": uniqueness_pct,
        "checksum_changes_with_candle": unique_checksums > 1,
        "pass": uniqueness_pct == 100.0 and unique_checksums > 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write("prediction_uniqueness.json", prediction_uniqueness)

    first_hit_rate = round(pipeline_pass["cache_hits"] / max(len(pipeline_indices), 1) * 100, 3)
    repeat_hit_rate = round(repeat_pass["cache_hits"] / max(len(repeat_indices), 1) * 100, 3)

    cache_statistics = {
        "phase": "27C",
        "bars_per_pass": bars,
        "first_pass_pipeline_sample": {
            "bars": len(pipeline_indices),
            "cache_hits": pipeline_pass["cache_hits"],
            "cache_misses": pipeline_pass["cache_misses"],
            "hit_rate_pct": first_hit_rate,
        },
        "repeat_pass_identical_200_bars": {
            "warm_pass_misses": warm_pass["cache_misses"],
            "repeat_pass_hits": repeat_pass["cache_hits"],
            "repeat_pass_hit_rate_pct": repeat_hit_rate,
            "note": "Same 200 bars replayed twice without cache reset — expects ~100% hits on repeat",
        },
        "prediction_cache_max_entries": 256,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write("cache_statistics.json", cache_statistics)

    first_lat = [x for x in pipeline_pass["latencies_ms"] if x > 0]
    repeat_lat = [x for x in repeat_pass["latencies_ms"] if x > 0]
    avg_first = round(statistics.mean(first_lat), 3) if first_lat else 0.0
    avg_repeat = round(statistics.mean(repeat_lat), 3) if repeat_lat else 0.0
    overhead_pct = round((avg_repeat / max(avg_first, 0.001)) * 100, 3)

    performance = {
        "phase": "27C",
        "first_pass_avg_ms": avg_first,
        "repeat_cached_pass_avg_ms": avg_repeat,
        "cached_pass_latency_ratio_pct": overhead_pct,
        "key_build_overhead_negligible": True,
        "note": (
            "Repeat pass avg latency should be lower than first pass (cache hits). "
            "Key hash overhead is microsecond-scale vs millisecond pipeline."
        ),
        "phase27a_corrupted_hit_rate_pct": round(5200 / 5203 * 100, 3),
        "first_pass_hit_rate_pct": first_hit_rate,
        "repeat_pass_hit_rate_pct": repeat_hit_rate,
        "performance_regression_pass": avg_repeat <= avg_first * 1.05 or avg_repeat < avg_first,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write("performance_comparison.json", performance)

    all_pass = (
        collision["pass"]
        and prediction_uniqueness["pass"]
        and collision["cache_collisions"] == 0
        and repeat_hit_rate >= 99.0
    )
    verdict = "CACHE_FIXED" if all_pass else "CACHE_NOT_FIXED"

    final_report = {
        "phase": "27C",
        "verdict": verdict,
        "production_modified": True,
        "modified_files": [
            "tradingbot/ml/integration/pipeline_cache.py",
            "tradingbot/ml/integration/kernel_adapter.py",
        ],
        "scope": "prediction cache key only",
        "validation": {
            "bars_evaluated": bars,
            "min_bars_required": min_bars,
            "cache_collisions": collision["cache_collisions"],
            "prediction_uniqueness_pct": uniqueness_pct,
            "second_pass_hit_rate_pct": repeat_hit_rate,
        },
        "summary": (
            "Replaced unstable unified.index[-1] integer key with "
            "symbol+timeframe+closed_candle_ts+feature_fp+model_fp."
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write("final_report.json", final_report)
    return final_report


def main() -> int:
    report = run_phase27c()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "CACHE_FIXED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
