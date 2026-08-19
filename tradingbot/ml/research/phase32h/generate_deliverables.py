"""Phase 32H — read-only feature pipeline integrity audit deliverables generator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
OUT = PROJECT_ROOT
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Load measurements if present
MEASURE_PATH = PROJECT_ROOT / "_phase32h_measure.json"
MEASURE = json.loads(MEASURE_PATH.read_text(encoding="utf-8")) if MEASURE_PATH.exists() else {}


def write(name: str, data: dict) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    unified_cols = MEASURE.get("unified_columns", [])
    costs = MEASURE.get("costs", {})

    lineage = {
        "timestamp_utc": NOW,
        "chain": [
            {"stage": "MT5_Candle", "source": "Mt5MarketDataAdapter / CandleStore parquet", "output": "OHLCV DataFrame"},
            {"stage": "normalize_candles_index", "file": "tradingbot/ml/research/phase13_9/candle_prepare.py", "output": "UTC DatetimeIndex OHLCV"},
            {"stage": "true_range_series", "file": "candle_prepare.py", "output": "shared TR series (optimized path)"},
            {"stage": "build_ml_features", "file": "tradingbot/ml/research/trend_ml/feature_builder.py", "output": "TREND_ML_FEATURE_COLUMNS + candle_momentum"},
            {"stage": "compute_regime_features_from_candles", "file": "tradingbot/ml/research/regime_detector/regime_features.py", "output": "REGIME_FEATURE_COLUMNS"},
            {"stage": "build_unified_frame", "file": "tradingbot/ml/research/phase13_9/unified_features.py", "output": "merged trend+regime+phase99+regime label"},
            {"stage": "PipelineCache.get_unified_frame", "file": "tradingbot/ml/integration/pipeline_cache.py", "output": "cached unified frame (multi-slot LRU)"},
            {"stage": "attach_top5_features", "file": "tradingbot/ml/research/phase17b/top5_features.py", "output": "5 v41 features", "condition": "TREND_ENGINE_V41_ID"},
            {"stage": "build_market_context", "file": "tradingbot/ml/decision_engine/validation.py", "output": "MarketContext"},
            {"stage": "ResearchCalibratedAdapter.decide", "file": "tradingbot/ml/research/phase14_6/research_calibrator.py", "output": "calibrated decision"},
            {"stage": "ConfidenceMapper.map", "file": "tradingbot/ml/confidence_mapping/confidence_mapper.py", "output": "mapped confidence"},
            {"stage": "TradeQualityAdapter.evaluate", "file": "tradingbot/ml/trade_quality/adapter.py", "output": "quality+risk gate"},
            {"stage": "UnifiedSignal", "file": "tradingbot/ml/phase15a/unified_signal.py", "output": "ML signal"},
        ],
        "parallel_paths": [
            {"name": "domain_indicators", "file": "tradingbot/domain/indicators.py", "consumer": "PriceActionStrategy + meta-labeler", "not_unified": True},
            {"name": "offline_FeatureBuilder", "file": "tradingbot/ml/features/builder.py", "consumer": "dataset v2 / training", "not_unified": True},
        ],
    }

    dependency_graph = {
        "timestamp_utc": NOW,
        "nodes": [
            {"id": "candles", "type": "source"},
            {"id": "trend_features", "type": "builder", "creates": ["ema*", "adx", "atr", "rsi", "macd_histogram", "breakout_distance", "hh/ll counts"]},
            {"id": "regime_features", "type": "builder", "creates": ["regime_*", "atr_value", "volatility", "spread_pips", "ema200_distance"]},
            {"id": "phase99_merge", "type": "merge", "creates": ["phase99_*"], "depends": ["dataset_v2"]},
            {"id": "regime_label", "type": "classifier", "creates": ["regime"], "function": "rule_classify_row"},
            {"id": "top5", "type": "builder", "creates": ["adx_acceleration", "swing_efficiency", "fractal_dimension_proxy", "trend_age", "ema_curvature"]},
            {"id": "range_engine", "type": "consumer", "model": "phase9_9", "inputs": 4},
            {"id": "trend_engine_v41", "type": "consumer", "model": "trend_rf_v41", "inputs": 16},
            {"id": "calibration", "type": "transform", "inputs": ["confidence scalars"]},
            {"id": "signal", "type": "output"},
        ],
        "edges": [
            {"from": "candles", "to": "trend_features"},
            {"from": "candles", "to": "regime_features"},
            {"from": "trend_features", "to": "unified_frame"},
            {"from": "regime_features", "to": "unified_frame"},
            {"from": "dataset_v2", "to": "phase99_merge"},
            {"from": "phase99_merge", "to": "unified_frame"},
            {"from": "unified_frame", "to": "regime_label"},
            {"from": "unified_frame", "to": "top5"},
            {"from": "unified_frame", "to": "range_engine"},
            {"from": "unified_frame", "to": "trend_engine_v41"},
            {"from": "range_engine", "to": "calibration"},
            {"from": "trend_engine_v41", "to": "calibration"},
            {"from": "calibration", "to": "signal"},
        ],
    }

    creator_map = {
        "timestamp_utc": NOW,
        "features": {
            "open/high/low/close": {"created": "compute_trend_features", "file": "trend_features.py:117-123"},
            "atr": {"created": "_atr_series", "files": ["trend_features.py:34-39", "regime_features.py:34-39"], "duplicated": True},
            "adx": {"created": "_adx_series", "files": ["trend_features.py:42-57", "regime_features.py:55-71"], "duplicated": True},
            "atr_percentile": {"created": "_atr_percentile_series", "duplicated": True},
            "ema20/50/200": {"created": "compute_trend_features", "normalized": "ema slopes /atr"},
            "rsi": {"created": "compute_trend_features", "fillna": 50.0},
            "macd_histogram": {"created": "compute_trend_features", "normalized": "raw"},
            "candle_momentum": {"created": "build_ml_features", "file": "feature_builder.py"},
            "phase99_*": {"created": "_attach_phase99_columns", "source": "dataset_v2 parquet", "file": "unified_features.py:72-81"},
            "regime": {"created": "attach_regime_labels", "function": "rule_classify_row", "recomputed": True},
            "top5_*": {"created": "attach_top5_features", "file": "top5_features.py:73-93"},
            "spread_pips": {"created": "regime_features", "hardcoded": 0.0, "note": "not from MT5 spread in unified path"},
            "confidence": {"created": "DecisionOrchestrator/ConfidenceEngine", "not_a_column": True},
        },
    }

    consumer_map = {
        "timestamp_utc": NOW,
        "range_ml_phase9_9": ["candle_direction", "structure_distance", "ema50_slope", "ema_cross_state"],
        "trend_ml_v41": [
            "ema20_slope", "ema50_slope", "ema_alignment", "adx", "atr_percentile", "rsi",
            "macd_histogram", "breakout_distance", "higher_high_count", "lower_low_count", "candle_momentum",
            "adx_acceleration", "swing_efficiency", "fractal_dimension_proxy", "trend_age", "ema_curvature",
        ],
        "rule_classify_row": ["spread_pips", "atr_percentile", "adx", "trend_strength", "ema50_slope", "volatility"],
        "apply_profitability_filters": ["rsi", "adx"],
        "TradeQualityAdapter": ["spread_pips", "atr_percentile"],
        "dead_on_unified_frame": ["open", "ema200", "ema200_distance", "range_pct", "regime_adx", "regime_atr_percentile", "regime_ema20_slope", "regime_ema50_slope", "regime_higher_high_count", "regime_lower_low_count"],
        "registry_only_not_on_unified": 41,
    }

    duplicate_report = {
        "timestamp_utc": NOW,
        "duplicates": [
            {"pair": ["compute_trend_features._adx_series", "compute_regime_features._adx_series"], "overlap": "full ADX recompute", "shared_tr_mitigation": "optimized path passes _true_range", "still_duplicated": True},
            {"pair": ["compute_trend_features._atr_series", "compute_regime_features._atr_series"], "overlap": "ATR rolling mean", "shared_tr_mitigation": True},
            {"pair": ["trend adx column", "regime_adx column"], "same_source_different_column": True, "rounding_diff": "regime rounds to 4 decimals"},
            {"pair": ["attach_regime_labels", "pipeline_cache regime loop", "top5 regime loop", "build_market_context rule_classify_row"], "function": "rule_classify_row", "calls_per_unified_build": "1 batch + up to 300 row loop if regime missing + 1 per context"},
            {"pair": ["domain/indicators.compute_indicators", "unified trend path"], "overlap": "ADX/ATR/EMA/RSI/MACD", "parallel_world": True},
            {"pair": ["offline FeatureBuilder (45 cols)", "unified frame"], "overlap": "partial semantic overlap", "parallel_world": True},
            {"pair": ["ema50_slope trend column", "phase99_ema50_slope"], "intentional_duplicate": True, "reason": "TREND_PROTECTED_COLUMNS — range uses frozen copy"},
        ],
        "duplicate_count_estimate_per_unified_build": {
            "adx_passes": 2,
            "atr_passes": 2,
            "rule_classify_row_max": 301,
        },
    }

    normalization_report = {
        "timestamp_utc": NOW,
        "families": {
            "price_ohlc": {"method": "raw float", "normalized": False},
            "atr": {"method": "TR rolling 14", "slopes_normalized_by": "atr"},
            "adx": {"method": "Wilder-style DX rolling", "fillna": 0.0},
            "ema_slopes": {"method": "ema.diff(5)/atr", "fillna": 0.0},
            "rsi": {"method": "rolling 14", "fillna": 50.0, "bounds": "0-100"},
            "macd_histogram": {"method": "raw EMA difference", "offline_alternate": "divided by ATR in momentum.py"},
            "atr_percentile": {"method": "rolling percentile rank 252", "fillna": 50.0},
            "top5": {"method": "rolling derived", "model_scaler": "StandardScaler at inference"},
            "phase99": {"method": "frozen dataset values", "no_runtime_normalization": True},
            "trend_rf_v41_inference": {"method": "bundle StandardScaler", "file": "trend_bundle.py"},
            "training_offline": {"method": "StandardScaler train-only", "file": "training/feature_pipeline.py"},
        },
        "silent_fillna_risks": [
            {"feature": "rsi", "fillna": 50.0, "risk": "masks insufficient warmup as neutral"},
            {"feature": "adx", "fillna": 0.0, "risk": "masks warmup as RANGE-like low trend"},
            {"feature": "atr_percentile", "fillna": 50.0, "risk": "neutral volatility assumption"},
            {"feature": "spread_pips", "value": 0.0, "risk": "regime classifier never sees abnormal spread from unified path"},
        ],
    }

    cache_consistency = {
        "timestamp_utc": NOW,
        "caches": [
            {"name": "PipelineCache._feature_cache_slots", "key": "symbol|tf|closed_ts|dataset_checksum|feature_version", "max_slots": 64, "invalidation": "dataset file fingerprint change", "stale_risk": "LOW if checksum in key"},
            {"name": "PipelineCache._top5_cache", "key": "feature_cache_key|pre_top5_checksum|feature_version", "stale_risk": "LOW"},
            {"name": "PipelineCache._market_context_cache", "key": "symbol|tf|closed_ts|row_fp|model_fp|bar_index", "stale_risk": "LOW"},
            {"name": "PipelineCache._prediction_cache", "key": "row_key", "stale_risk": "LOW — separate from features"},
            {"name": "DatasetMemoryCache", "key": "parquet path", "invalidation": "mtime+size", "stale_risk": "LOW"},
        ],
        "measured_cache_stats": MEASURE.get("cache_stats", {}),
        "can_two_values_same_candle": {
            "across_timeframes": False,
            "across_cache_hit_miss": False,
            "across_phase99_sources": True,
            "note": "phase99_* from dataset merge vs FeatureBuilder fallback can differ when dataset v2 absent",
        },
    }

    timeframe_integrity = {
        "timestamp_utc": NOW,
        "cache_key_includes_timeframe": True,
        "per_tf_isolated_slots": True,
        "contamination_risk": "LOW after Phase 32G multi-slot cache",
        "htf_features_on_unified": False,
        "htf_in_offline_registry": ["h4_trend_bias", "h4_structure_direction", "m15_market_state", "m5_entry_context"],
        "note": "Unified frame built per symbol×timeframe independently; no cross-TF merge in live path",
    }

    symbol_integrity = {
        "timestamp_utc": NOW,
        "cache_key_includes_symbol": True,
        "default_symbol": "XAUUSD",
        "contamination_risk": "LOW",
        "dataset_store_scoped": "symbol+timeframe path",
    }

    leakage_report = {
        "timestamp_utc": NOW,
        "look_ahead": {
            "unified_frame_tail_300": {"status": "PASS", "note": "causal rolling within window"},
            "exclude_forming_bar": {"status": "PASS", "file": "domain/ohlcv.py:61-69"},
            "label_from_future_candles": {"status": "PASS", "scope": "labels only, not features"},
            "htf_align_closed_slice": {"status": "PASS", "file": "ml/features/align.py"},
        },
        "future_leakage": {"status": "NOT_FOUND_IN_LIVE_PATH"},
        "medium_risks": [
            {"risk": "phase99 timestamp left-merge", "file": "unified_features.py:81", "condition": "misaligned dataset timestamps could join wrong row"},
            {"risk": "phase99 fallback FeatureBuilder", "file": "unified_feature_input.py:152-154", "condition": "different feature semantics when dataset v2 missing"},
        ],
        "training_scaler_fit": {"status": "MITIGATED", "method": "train-only StandardScaler"},
    }

    unused = {
        "timestamp_utc": NOW,
        "on_unified_frame_unused_by_ml_kernel": [
            "open", "ema200", "ema200_distance", "range_pct",
            "regime_adx", "regime_atr_percentile", "regime_ema20_slope", "regime_ema50_slope",
            "regime_higher_high_count", "regime_lower_low_count",
        ],
        "count": 9,
        "note": "Present for diagnostics/parity; not read by production consumers",
    }

    dead = {
        "timestamp_utc": NOW,
        "registry_features_not_on_unified": 41,
        "examples": ["h4_trend_bias", "bos_state", "tick_volume_proxy", "spread_spike", "body_ratio"],
        "phase99_columns_missing_when_no_dataset_v2": ["phase99_ema50_slope", "phase99_candle_direction", "phase99_structure_distance", "phase99_ema_cross_state"],
        "measured_env": "dataset v2 absent for M5/M15/H4 in audit environment",
    }

    memory_usage = {
        "timestamp_utc": NOW,
        "measured": MEASURE.get("memory_bytes", {}),
        "feature_cache_slots_after_warm": MEASURE.get("cache_stats", {}).get("feature_cache_slots"),
        "unified_frame_columns": MEASURE.get("unified_col_count"),
        "unified_frame_rows": MEASURE.get("costs", {}).get("build_unified_frame", {}).get("rows"),
    }

    creation_cost = {
        "timestamp_utc": NOW,
        "measured_ms": costs,
        "phase32f_reference_ms": {
            "build_unified_frame_cold_p95": 678.365,
            "get_unified_frame_hit_avg": 81.197,
            "attach_top5_avg": 23.473,
        },
        "phase32g_post_optimization": {
            "get_unified_frame_hit_ms": costs.get("PipelineCache.get_unified_frame_hit", {}).get("ms"),
        },
        "reuse_count_after_cache": MEASURE.get("cache_stats", {}).get("feature_cache_hits"),
    }

    verdict = "FEATURE_DUPLICATION_FOUND"
    verdict_reason = (
        "Confirmed duplicate indicator passes (ADX/ATR/atr_percentile/swing counts) in trend+regime builders; "
        "rule_classify_row invoked multiple times per unified build; three parallel feature worlds "
        "(domain indicators, unified frame, offline FeatureBuilder). No confirmed look-ahead leakage. "
        "Phase99 source inconsistency when dataset v2 absent (FeatureBuilder fallback)."
    )

    final_report = {
        "phase": "32H",
        "title": "Feature Pipeline Integrity Audit",
        "timestamp_utc": NOW,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "checks": {
            "future_leakage": "NOT_FOUND",
            "look_ahead": "MITIGATED",
            "duplicated_computation": "FOUND",
            "inconsistent_normalization": "PARTIAL — MACD offline vs unified; spread_pips=0",
            "feature_drift": "LOW with Phase 32G cache keys",
            "stale_cache": "LOW",
            "mixed_timeframe_contamination": "LOW post-32G",
            "mixed_symbol_contamination": "LOW",
            "nan_propagation": "PASS — no NaN in measured unified frame last row",
            "silent_fillna": "FOUND — rsi/adx/atr_percentile defaults",
            "hidden_overwrite": "MITIGATED — TREND_PROTECTED_COLUMNS + phase99_ prefix",
            "two_values_same_candle": "POSSIBLE — phase99 source fallback; regime_adx vs adx rounding",
        },
        "unified_column_count": len(unified_cols),
        "unified_columns": unified_cols,
        "deliverables": [
            "feature_lineage.json", "feature_dependency_graph.json", "feature_creator_map.json",
            "feature_consumer_map.json", "feature_duplicate_report.json", "feature_normalization_report.json",
            "feature_cache_consistency.json", "feature_timeframe_integrity.json", "feature_symbol_integrity.json",
            "feature_leakage_report.json", "unused_features.json", "dead_features.json",
            "feature_memory_usage.json", "feature_creation_cost.json", "phase32h_final_report.json",
        ],
        "next_recommendation": "Phase 32I — fuse trend+regime indicator pass (RISKY) OR document phase99 dataset v2 as hard dependency for range engine parity",
    }

    write("feature_lineage.json", lineage)
    write("feature_dependency_graph.json", dependency_graph)
    write("feature_creator_map.json", creator_map)
    write("feature_consumer_map.json", consumer_map)
    write("feature_duplicate_report.json", duplicate_report)
    write("feature_normalization_report.json", normalization_report)
    write("feature_cache_consistency.json", cache_consistency)
    write("feature_timeframe_integrity.json", timeframe_integrity)
    write("feature_symbol_integrity.json", symbol_integrity)
    write("feature_leakage_report.json", leakage_report)
    write("unused_features.json", unused)
    write("dead_features.json", dead)
    write("feature_memory_usage.json", memory_usage)
    write("feature_creation_cost.json", creation_cost)
    write("phase32h_final_report.json", final_report)

    print(json.dumps({"verdict": verdict, "files": len(final_report["deliverables"])}, indent=2))


if __name__ == "__main__":
    main()
