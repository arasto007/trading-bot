"""Phase 24G — safe internal optimization validation."""

from __future__ import annotations

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


def build_duplicate_computation_report() -> dict[str, Any]:
    return {
        "phase": "24G",
        "profiled_function": "build_unified_frame",
        "duplicate_paths": [
            {
                "path_a": "build_ml_features → compute_trend_features",
                "path_b": "compute_regime_features_from_candles",
                "shared_work_eliminated": [
                    "normalize_candles_index (copy + sort)",
                    "true_range_series (used by trend ATR/ADX and regime ATR/ADX)",
                ],
                "still_computed_separately": [
                    "EMA stacks (trend-only)",
                    "RSI/MACD/breakout (trend-only)",
                    "volatility/range_pct/ema200_distance (regime-only)",
                ],
            }
        ],
        "duplicated_indicators_exact_list": [
            {"indicator": "candle_normalize", "trend": "_normalize", "regime": "_normalize_candles", "action": "shared once"},
            {"indicator": "true_range", "trend": "_atr_series/_adx_series internal", "regime": "_atr_series/_adx_series internal", "action": "computed once, passed to both"},
            {"indicator": "atr", "trend": "_atr_series", "regime": "_atr_series", "action": "same tr input, separate rolling (min_periods preserved)"},
            {"indicator": "adx", "trend": "_adx_series", "regime": "_adx_series", "action": "same tr input, separate rolling"},
            {"indicator": "atr_percentile", "trend": "_atr_percentile_series", "regime": "_atr_percentile_series", "action": "still separate (depends on atr output)"},
            {"indicator": "ema20_slope", "trend": "_ema_slope(ema20, atr)", "regime": "_ema_slope(close, 20, atr)", "action": "still separate (regime rounding differs)"},
            {"indicator": "ema50_slope", "trend": "_ema_slope(ema50, atr)", "regime": "_ema_slope(close, 50, atr)", "action": "still separate"},
            {"indicator": "higher_high_count", "trend": "rolling max count", "regime": "_swing_counts", "action": "still separate"},
            {"indicator": "lower_low_count", "trend": "rolling min count", "regime": "_swing_counts", "action": "still separate"},
        ],
        "generated_utc": _utc_now(),
    }


def build_merge_optimization() -> dict[str, Any]:
    return {
        "phase": "24G",
        "before": {
            "pattern": "for col in REGIME_FEATURE_COLUMNS: base[[timestamp]].merge(...) per column",
            "merge_count": 12,
            "source": "unified_features.py legacy loop",
        },
        "after": {
            "pattern": "_attach_regime_columns_batch — single merge with renamed columns",
            "merge_count": 1,
            "phase99_merge": "single merge unchanged",
        },
        "formula_changes": False,
        "generated_utc": _utc_now(),
    }


def build_copy_reduction() -> dict[str, Any]:
    return {
        "phase": "24G",
        "removed_or_avoided": [
            {"op": "base.copy() before regime loop", "action": "removed in optimized path — batch merge returns new frame"},
            {"op": "duplicate normalize_candles", "action": "single normalize_candles_index per call"},
            {"op": "duplicate true_range inside trend+regime", "action": "single true_range_series passed via _true_range"},
            {"op": "per-column timestamp merge slices", "action": "replaced with one merge"},
        ],
        "retained_required": [
            "final sort_values + reset_index",
            "phase99 feat.copy() before timestamp convert",
            "regime merge_frame.copy() for rename safety",
        ],
        "generated_utc": _utc_now(),
    }


def run_validation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.research.phase13_9.unified_features import (
        ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME,
        _build_unified_frame_legacy,
        _build_unified_frame_optimized,
        build_unified_frame,
    )
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.ml.research.research_utils import dataset_content_fingerprint

    bar_counts = (50,) if quick else (100, 500, 1000)
    latency_iters = 15 if quick else 60

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    symbol, timeframe = "XAUUSD", "M5"

    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles_raw is None or dataset is None:
        return {"error": "missing_data", "verdict": "ROLLBACK_REQUIRED"}

    norm = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=365))
    warmup = 250
    max_available = max(0, len(norm) - warmup - 1)

    feature_results: dict[str, Any] = {}
    all_pass = True
    for n_bars in bar_counts:
        n = min(n_bars, max_available)
        mismatches = 0
        for bar_index in range(warmup, warmup + n):
            chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
            legacy = _build_unified_frame_legacy(chunk, dataset)
            optimized = _build_unified_frame_optimized(chunk, dataset)
            try:
                pd.testing.assert_frame_equal(
                    legacy.reset_index(drop=True),
                    optimized.reset_index(drop=True),
                    check_exact=True,
                    check_dtype=True,
                )
            except AssertionError:
                mismatches += 1
                all_pass = False
        feature_results[str(n_bars)] = {
            "bars_tested": n,
            "frame_mismatches": mismatches,
            "all_frames_equal": mismatches == 0,
        }

    # Latency on stable 300-bar window
    sample_index = min(warmup + 400, len(norm) - 1)
    chunk = norm.iloc[max(0, sample_index + 1 - 300) : sample_index + 1]
    legacy_times: list[float] = []
    opt_times: list[float] = []
    for _ in range(latency_iters):
        t0 = time.perf_counter()
        _build_unified_frame_legacy(chunk, dataset)
        legacy_times.append((time.perf_counter() - t0) * 1000)
    for _ in range(latency_iters):
        t0 = time.perf_counter()
        _build_unified_frame_optimized(chunk, dataset)
        opt_times.append((time.perf_counter() - t0) * 1000)

    legacy_stats = _stats(legacy_times)
    opt_stats = _stats(opt_times)
    savings_p95 = legacy_stats["p95_ms"] - opt_stats["p95_ms"]

    # Prediction parity
    os.environ[TREND_VERSION_ENV] = "v41"
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "false"
    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    ka_off = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol=symbol))
    market = MarketKey(symbol=symbol, timeframe=timeframe)

    pred_samples: list[dict[str, Any]] = []
    pred_pass = True
    sample_indices = list(range(warmup, min(warmup + (5 if quick else 20), len(norm)), 2))
    for bar_index in sample_indices:
        chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
        PipelineCache.reset()
        os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "false"
        sig_off = ka_off.produce_unified_signal(market, chunk)

        PipelineCache.reset()
        os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "true"
        ka_on = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol=symbol))
        sig_on = ka_on.produce_unified_signal(market, chunk)

        match = (
            sig_off.direction == sig_on.direction
            and sig_off.confidence == sig_on.confidence
            and sig_off.regime == sig_on.regime
            and sig_off.quality == sig_on.quality
            and sig_off.risk == sig_on.risk
        )
        pred_pass = pred_pass and match
        pred_samples.append(
            {
                "bar_index": bar_index,
                "direction_match": sig_off.direction == sig_on.direction,
                "confidence_match": sig_off.confidence == sig_on.confidence,
                "regime_match": sig_off.regime == sig_on.regime,
                "quality_match": sig_off.quality == sig_on.quality,
                "risk_match": sig_off.risk == sig_on.risk,
            }
        )

    # Rollback validation
    os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "false"
    rollback_frame = build_unified_frame(chunk, dataset)
    legacy_frame = _build_unified_frame_legacy(chunk, dataset)
    rollback_ok = legacy_frame.reset_index(drop=True).equals(rollback_frame.reset_index(drop=True))

    os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "true"

    meaningful = savings_p95 >= 5.0
    if all_pass and pred_pass and rollback_ok and meaningful:
        verdict = "SAFE_DEPLOYED"
    elif all_pass and pred_pass and rollback_ok:
        verdict = "NO_MEANINGFUL_IMPROVEMENT"
    else:
        verdict = "ROLLBACK_REQUIRED"

    return {
        "duplicate_computation_report.json": build_duplicate_computation_report(),
        "merge_optimization.json": build_merge_optimization(),
        "copy_reduction.json": build_copy_reduction(),
        "latency_before_after.json": {
            "phase": "24G",
            "iterations": latency_iters,
            "before_legacy": legacy_stats,
            "after_optimized": opt_stats,
            "savings_p95_ms": round(savings_p95, 4),
            "savings_pct_p95": round(100 * savings_p95 / legacy_stats["p95_ms"], 2)
            if legacy_stats["p95_ms"]
            else 0,
            "generated_utc": _utc_now(),
        },
        "feature_parity.json": {
            "phase": "24G",
            "bar_count_results": feature_results,
            "all_pass": all_pass,
            "dataset_fingerprint": dataset_content_fingerprint(dataset),
            "generated_utc": _utc_now(),
        },
        "prediction_parity.json": {
            "phase": "24G",
            "samples": pred_samples,
            "all_match": pred_pass,
            "generated_utc": _utc_now(),
        },
        "rollback_validation.json": {
            "phase": "24G",
            "env_flag": ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME,
            "default": True,
            "rollback_value": "false",
            "rollback_matches_legacy": rollback_ok,
            "generated_utc": _utc_now(),
        },
        "phase24g_final_report.json": {
            "phase": "24G",
            "verdict": verdict,
            "production_modified": True,
            "summary": (
                f"Optimized build_unified_frame: {verdict}. "
                f"Feature parity: {all_pass}. Prediction parity: {pred_pass}. "
                f"p95 savings: {round(savings_p95, 2)} ms."
            ),
            "env_flag": ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME,
            "generated_utc": _utc_now(),
        },
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
        "verdict": artifacts["phase24g_final_report.json"]["verdict"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 24G unified frame optimization validation")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    print(json.dumps(write_deliverables(quick=args.quick), indent=2))
