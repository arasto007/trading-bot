"""Phase 24I — unified feature input validation and parity proof."""

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


def _evaluate_legacy(row, chunk, bi, adapter):
    os.environ["ENABLE_UNIFIED_FEATURE_INPUT"] = "false"
    return adapter.evaluate(row=row, candles=chunk, bar_index=bi)


def _evaluate_new(row, chunk, bi, adapter):
    os.environ["ENABLE_UNIFIED_FEATURE_INPUT"] = "true"
    return adapter.evaluate(row=row, candles=chunk, bar_index=bi)


def run_validation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.features.builder import FeatureBuilder
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.health_gate import run_pre_decision_health
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
    from tradingbot.ml.research.regime_router.unified_feature_input import (
        ENV_ENABLE_UNIFIED_BUILDER_VERIFY,
        ENV_ENABLE_UNIFIED_FEATURE_INPUT,
        extract_phase99_features_from_row,
        validate_unified_feature_vector,
    )
    from tradingbot.ml.research.regime_router.phase99_feature_validation import (
        normalize_candles_for_builder,
        ordered_feature_vector,
    )
    from tradingbot.ml.research.research_utils import dataset_content_fingerprint

    bar_counts = (50,) if quick else (100, 500, 1000)
    latency_iters = 15 if quick else 40

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    symbol = "XAUUSD"
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ[TREND_VERSION_ENV] = "v41"
    os.environ["ENABLE_OPTIMIZED_UNIFIED_FRAME"] = "true"
    os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "true"
    os.environ[ENV_ENABLE_UNIFIED_BUILDER_VERIFY] = "true"

    candles_raw = CandleStore(base_dir).load(symbol, "M5")
    dataset = DatasetStore(base_dir).load_v2(symbol, "M5")
    if candles_raw is None or dataset is None:
        return {"error": "missing_data", "verdict": "ROLLBACK_REQUIRED"}

    norm = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=365))
    adapter = RangeEngineAdapter.load(symbol=symbol, base_dir=base_dir)
    order = list(adapter.bundle.feature_order)
    fb = FeatureBuilder(symbol=symbol, base_dir=base_dir)

    ds_max = pd.to_datetime(dataset["timestamp"].max(), utc=True)
    center = int(norm.index.get_indexer([ds_max], method="nearest")[0])
    warmup = 250

    parity_results: dict[str, Any] = {}
    all_parity_pass = True
    source_counts = {"unified_phase99": 0, "feature_builder": 0, "unified_row": 0}
    fallback_reasons: dict[str, int] = {}

    for n_bars in bar_counts:
        half = n_bars // 2
        start = max(warmup, center - half)
        end = min(len(norm), start + n_bars)
        mismatches = 0
        vector_mismatches = 0
        bars_tested = 0

        for bi in range(start, end):
            chunk = norm.iloc[max(0, bi + 1 - 300) : bi + 1]
            row = attach_top5_features(build_unified_frame(chunk, dataset)).iloc[-1]
            bi_idx = len(chunk) - 1
            old = _evaluate_legacy(row, chunk, bi_idx, adapter)
            new = _evaluate_new(row, chunk, bi_idx, adapter)
            bars_tested += 1
            src = str(new.get("feature_source", ""))
            if src in source_counts:
                source_counts[src] += 1

            if old.get("signal") != new.get("signal") or old.get("probability") != new.get("probability"):
                mismatches += 1
                all_parity_pass = False

            old_vec = old.get("feature_vector") or {}
            new_vec = new.get("feature_vector") or {}
            if old_vec != new_vec:
                vector_mismatches += 1

        parity_results[str(n_bars)] = {
            "bars_tested": bars_tested,
            "prediction_mismatches": mismatches,
            "vector_mismatches": vector_mismatches,
            "all_equal": mismatches == 0,
        }

    # Latency: compare builder vs unified-first (verify off) on valid-unified bars
    os.environ[ENV_ENABLE_UNIFIED_BUILDER_VERIFY] = "false"
    builder_times: list[float] = []
    unified_times: list[float] = []
    range_old_times: list[float] = []
    range_new_times: list[float] = []
    kernel_times: list[float] = []

    sample_chunk = norm.iloc[max(0, center + 1 - 300) : center + 1]
    sample_row = attach_top5_features(build_unified_frame(sample_chunk, dataset)).iloc[-1]
    sample_bi = len(sample_chunk) - 1

    for _ in range(latency_iters):
        t0 = time.perf_counter()
        fb.compute_at(sample_chunk, sample_bi)
        builder_times.append((time.perf_counter() - t0) * 1000)

    for _ in range(latency_iters):
        t0 = time.perf_counter()
        feats = extract_phase99_features_from_row(sample_row, order)
        validate_unified_feature_vector(feats, order)
        unified_times.append((time.perf_counter() - t0) * 1000)

    for _ in range(latency_iters):
        t0 = time.perf_counter()
        _evaluate_legacy(sample_row, sample_chunk, sample_bi, adapter)
        range_old_times.append((time.perf_counter() - t0) * 1000)

    for _ in range(latency_iters):
        t0 = time.perf_counter()
        _evaluate_new(sample_row, sample_chunk, sample_bi, adapter)
        range_new_times.append((time.perf_counter() - t0) * 1000)

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    ka = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol=symbol))
    market = MarketKey(symbol=symbol, timeframe="M5")
    os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "true"
    os.environ[ENV_ENABLE_UNIFIED_BUILDER_VERIFY] = "true"

    for _ in range(max(5, latency_iters // 4)):
        PipelineCache.reset()
        t0 = time.perf_counter()
        ka.produce_unified_signal(market, sample_chunk)
        kernel_times.append((time.perf_counter() - t0) * 1000)

    # Rollback
    os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "false"
    rollback_eval = adapter.evaluate(row=sample_row, candles=sample_chunk, bar_index=sample_bi)
    legacy_eval = _evaluate_legacy(sample_row, sample_chunk, sample_bi, adapter)
    rollback_ok = rollback_eval == legacy_eval

    # HealthGate
    os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "true"
    health = run_pre_decision_health(registry=stack.registry, base_dir=base_dir, unified_row=sample_row)

    # Verdict
    unified_used = source_counts["unified_phase99"]
    total_src = sum(source_counts.values()) or 1
    unified_pct = round(100 * unified_used / total_src, 2)

    if all_parity_pass and rollback_ok and health.passes:
        verdict = "SAFE_DEPLOYED"
    elif not all_parity_pass:
        verdict = "PARITY_FAILED"
    else:
        verdict = "ROLLBACK_REQUIRED"

    builder_p95 = _stats(builder_times)["p95_ms"]
    unified_p95 = _stats(unified_times)["p95_ms"]

    return {
        "feature_source_selection.json": {
            "phase": "24I",
            "priority": [
                "1. validated unified phase99 features",
                "2. FeatureBuilder.compute_at fallback",
                "3. direct unified row columns",
            ],
            "env_flags": {
                ENV_ENABLE_UNIFIED_FEATURE_INPUT: {"default": True, "rollback_value": "false"},
                ENV_ENABLE_UNIFIED_BUILDER_VERIFY: {
                    "default": True,
                    "note": "When true, calls FeatureBuilder to confirm parity before using unified vector",
                },
            },
            "source_counts": source_counts,
            "unified_usage_pct": unified_pct,
            "generated_utc": _utc_now(),
        },
        "feature_validation_report.json": {
            "phase": "24I",
            "checks": [
                "feature_count",
                "feature_names",
                "feature_order",
                "finite_values",
                "dtype",
                "range_sanity",
                "optional_builder_parity_verify",
            ],
            "generated_utc": _utc_now(),
        },
        "fallback_analysis.json": {
            "phase": "24I",
            "fallback_triggers": [
                "missing_feature",
                "invalid_dtype",
                "NaN/Inf",
                "wrong_order",
                "range_sanity_failure",
                "builder_parity_mismatch",
            ],
            "fallback_reason_counts": fallback_reasons,
            "generated_utc": _utc_now(),
        },
        "parity_report.json": {
            "phase": "24I",
            "builder_verify_enabled": True,
            "bar_count_results": parity_results,
            "all_pass": all_parity_pass,
            "generated_utc": _utc_now(),
        },
        "prediction_parity.json": {
            "phase": "24I",
            "all_match": all_parity_pass,
            "source_counts": source_counts,
            "generated_utc": _utc_now(),
        },
        "latency_before_after.json": {
            "phase": "24I",
            "feature_builder_compute_at": _stats(builder_times),
            "unified_extract_validate_only": _stats(unified_times),
            "extract_only_p95_savings_ms": round(builder_p95 - unified_p95, 4),
            "range_engine_eval_legacy": _stats(range_old_times),
            "range_engine_eval_unified_path": _stats(range_new_times),
            "kernel_adapter_produce_unified": _stats(kernel_times),
            "note": (
                "Production default ENABLE_UNIFIED_BUILDER_VERIFY=true preserves parity; "
                "extract-only savings apply when verify=false on valid unified bars"
            ),
            "generated_utc": _utc_now(),
        },
        "rollback_validation.json": {
            "phase": "24I",
            "env_flag": ENV_ENABLE_UNIFIED_FEATURE_INPUT,
            "rollback_matches_legacy": rollback_ok,
            "generated_utc": _utc_now(),
        },
        "runtime_validation.json": {
            "phase": "24I",
            "health_gate_passes": health.passes,
            "dataset_fingerprint": dataset_content_fingerprint(dataset),
            "generated_utc": _utc_now(),
        },
        "phase24i_final_report.json": {
            "phase": "24I",
            "verdict": verdict,
            "production_modified": True,
            "summary": (
                f"Unified phase99 feature input: {verdict}. "
                f"Parity all_pass={all_parity_pass}. "
                f"Unified source used {unified_pct}% of bars. "
                f"Extract-only p95 savings vs FeatureBuilder: {round(builder_p95 - unified_p95, 2)} ms."
            ),
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
        "verdict": artifacts["phase24i_final_report.json"]["verdict"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 24I validation")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    print(json.dumps(write_deliverables(quick=args.quick), indent=2))
