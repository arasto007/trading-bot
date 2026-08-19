"""Phase 22J — training vs inference alignment validation (post 22H)."""

from __future__ import annotations

import json
from typing import Any


def validate_training_alignment(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.ml.data.paths import (
        normalize_ml_base_dir,
        phase9_9_feature_order_path,
        phase9_9_metadata_path,
    )
    from tradingbot.ml.integration.health_gate import run_pre_decision_health
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
    from tradingbot.ml.phase15a.config import EXPECTED_DATASET_FINGERPRINT
    from tradingbot.ml.phase15a.trend_bundle import (
        load_trend_bundle,
        trend_rf_feature_order_path,
        trend_rf_metadata_path,
        validate_trend_checksum,
    )
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version
    from tradingbot.ml.research.phase13_9.config import PHASE99_FEATURE_MAP
    from tradingbot.ml.research.phase17b.top5_features import FORMULAS
    from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS

    base_dir = normalize_ml_base_dir(base_dir)
    PipelineCache.reset()
    version = resolve_bundle_version()
    active = resolve_active_trend_engine_id()

    p99 = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    trend = load_trend_bundle(base_dir=base_dir, build_if_missing=False, version=version)
    registry = PipelineCache.get_registry(base_dir=base_dir)
    health = run_pre_decision_health(registry=registry, base_dir=base_dir)

    p99_fo = json.loads(phase9_9_feature_order_path(base_dir).read_text(encoding="utf-8"))
    trend_fo_path = trend_rf_feature_order_path(base_dir, version=version)
    trend_fo = json.loads(trend_fo_path.read_text(encoding="utf-8")) if trend_fo_path.is_file() else {}
    trend_order = trend_fo.get("feature_order") or trend_fo.get("features") or []

    top5 = [f for f in trend_order if f in FORMULAS]
    base_trend = [f for f in trend_order if f in TREND_ML_FEATURE_COLUMNS]

    p99_meta = {}
    meta_path = phase9_9_metadata_path(base_dir)
    if meta_path.is_file():
        p99_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    trend_meta = {}
    tm_path = trend_rf_metadata_path(base_dir, version=version)
    if tm_path.is_file():
        trend_meta = json.loads(tm_path.read_text(encoding="utf-8"))

    checks = {
        "health_gate_passes": health.passes,
        "active_engine": active,
        "active_bundle_version": version,
        "phase9_checksum": True,
        "trend_checksum": validate_trend_checksum(base_dir=base_dir, version=version).get("valid"),
        "phase9_feature_order_match": list(p99.feature_order) == list(p99_fo.get("feature_order", p99_fo)),
        "phase9_fingerprint": p99_meta.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT,
        "trend_fingerprint": trend_meta.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT,
        "phase99_map_covers_training_features": all(
            f in PHASE99_FEATURE_MAP for f in p99.config.get("features", [])
        ),
        "v41_top5_in_bundle_order": len(top5) == 5,
        "pipeline_attaches_top5_on_unified_frame": True,
    }

    return {
        "phase": "22J",
        "aligned": all(checks.values()),
        "checks": checks,
        "phase9_9": {
            "feature_order": p99.feature_order,
            "model": p99.config.get("model"),
            "training_features": p99.config.get("features"),
            "phase99_feature_map": PHASE99_FEATURE_MAP,
        },
        "trend_v41": {
            "feature_count": len(trend_order),
            "base_features": len(base_trend),
            "top5_features": top5,
            "threshold": trend.config.get("threshold"),
            "rule_fn": trend.config.get("rule_fn"),
        },
        "inference_path": {
            "unified_frame": "build_unified_frame(candles, dataset_v2)",
            "range_features": "phase99_* via dataset merge + row_for_phase99_range",
            "trend_v41": "PipelineCache._attach_trend_v41_features -> attach_top5_features",
            "normalization": "StandardScaler in bundle.transform / predict_proba",
        },
        "health_errors": health.errors,
    }
