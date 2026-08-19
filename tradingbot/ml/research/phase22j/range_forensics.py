"""Phase 22J — phase9_9 range engine forensics on Dataset A."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

import numpy as np

from tradingbot.ml.research.phase22f.config import RapidDataset


def _prob_bucket(p: float) -> str:
    if p < 0.45:
        return "sell_zone"
    if p <= 0.55:
        return "dead_zone_0.45_0.55"
    return "buy_zone"


async def profile_range_engine(
    dataset: RapidDataset,
    *,
    timeframe: str = "M5",
    stride: int = 5,
    warmup: int = 300,
) -> dict[str, Any]:
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
    from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
    from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
    from tradingbot.ml.research.phase22f.config import configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row
    from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter

    configure_research_env()
    PipelineCache.reset()
    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(legacy.get("BASE_DIR"))
    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    range_inner = RangeEngineAdapter.load(symbol="XAUUSD", base_dir=base_dir)

    frame = await load_ohlcv_for_dataset(dataset, timeframe)
    if frame is None or len(frame) < warmup + 10:
        return {"error": "no_data"}

    probs: list[float] = []
    bucket_counts: Counter[str] = Counter()
    hold_causes: Counter[str] = Counter()
    feature_zero_counts: Counter[str] = Counter()
    missing_feature_bars = 0
    range_regime_bars = 0
    t0 = time.perf_counter()

    for i in range(warmup, len(frame), max(1, stride)):
        window = frame.iloc[: i + 1]
        unified = PipelineCache.get_unified_frame(
            window, base_dir=base_dir, symbol="XAUUSD", timeframe=timeframe,
        )
        if unified.empty:
            continue
        row = unified.iloc[-1]
        regime = rule_classify_row(row)
        if regime != "RANGE":
            continue
        range_regime_bars += 1

        mapped = row_for_phase99_range(row)
        feats = range_inner._features_from_row(mapped)
        if feats is None:
            missing_feature_bars += 1
            hold_causes["missing_features"] += 1
            probs.append(0.5)
            bucket_counts["dead_zone_0.45_0.55"] += 1
            continue

        for f in bundle.feature_order:
            v = feats.get(f, 0.0)
            if abs(v) < 1e-9:
                feature_zero_counts[f] += 1

        prob = bundle.predict_proba(feats)
        probs.append(prob)
        bucket = _prob_bucket(prob)
        bucket_counts[bucket] += 1
        sig = range_inner.signal_engine.generate(prob).value
        if sig == "HOLD":
            if bucket == "dead_zone_0.45_0.55":
                hold_causes["prob_dead_zone"] += 1
            elif bucket == "sell_zone":
                hold_causes["below_sell_threshold"] += 1
            else:
                hold_causes["other"] += 1

        for src, dst in PHASE99_FEATURE_MAP.items():
            if dst in row.index and abs(float(row.get(dst, 0))) < 1e-9:
                feature_zero_counts[f"unified_{dst}"] += 1

    arr = np.array(probs) if probs else np.array([0.5])
    total = max(len(probs), 1)

    return {
        "phase": "22J",
        "engine": "phase9_9",
        "dataset": dataset.to_dict(),
        "timeframe": timeframe,
        "stride": stride,
        "range_regime_bars": range_regime_bars,
        "bars_scored": len(probs),
        "elapsed_sec": round(time.perf_counter() - t0, 1),
        "probability_stats": {
            "mean": round(float(arr.mean()), 4),
            "std": round(float(arr.std()), 4),
            "median": round(float(np.median(arr)), 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "pct_near_0.5": round(float(np.mean(np.abs(arr - 0.5) < 0.05)) * 100, 2),
        },
        "bucket_distribution": {k: {"count": v, "pct": round(v / total * 100, 2)} for k, v in bucket_counts.items()},
        "hold_causes": dict(hold_causes),
        "missing_feature_bars": missing_feature_bars,
        "feature_zero_counts": dict(feature_zero_counts.most_common(10)),
        "model_config": {
            "buy_threshold": range_inner.signal_engine.config.buy_threshold,
            "sell_threshold": range_inner.signal_engine.config.sell_threshold,
            "feature_order": bundle.feature_order,
            "model": bundle.config.get("model"),
            "training_regime": bundle.config.get("regime"),
        },
        "root_cause_hypothesis": _diagnose_root_cause(arr, hold_causes, feature_zero_counts, missing_feature_bars, total),
    }


def _diagnose_root_cause(arr, hold_causes, zero_counts, missing, total) -> dict[str, Any]:
    dead = hold_causes.get("prob_dead_zone", 0)
    near_half = float(np.mean(np.abs(arr - 0.5) < 0.05)) if len(arr) else 0
    causes = []
    if near_half > 0.5:
        causes.append("probability_compression")
    if sum(zero_counts.values()) > total * 0.3:
        causes.append("feature_distribution_zeros")
    if missing > 0:
        causes.append("feature_mapping_missing")
    if dead > total * 0.3:
        causes.append("symmetric_threshold_dead_zone")
    if not causes:
        causes.append("model_calibration")
    return {
        "primary": causes[0] if causes else "unknown",
        "all_observed": causes,
        "evidence": {
            "pct_probs_within_0.05_of_0.5": round(near_half * 100, 2),
            "dead_zone_holds": dead,
            "missing_feature_bars": missing,
        },
    }
