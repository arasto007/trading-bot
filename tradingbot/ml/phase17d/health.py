"""Phase 17D — bundle and registry health validation."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID, trend_rf_bundle_root
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum
from tradingbot.ml.phase17d.config import BUNDLE_ARTIFACTS
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, version_to_engine_id
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features


def validate_bundle_artifacts(*, base_dir: str | Path | None = None, version: str = "v41") -> dict[str, Any]:
    root = trend_rf_bundle_root(base_dir, version=version)
    present = [a for a in BUNDLE_ARTIFACTS if (root / a).is_file()]
    missing = [a for a in BUNDLE_ARTIFACTS if a not in present]
    checksum = validate_trend_checksum(base_dir=base_dir, version=version)
    order_path = root / "feature_order.json"
    stats_path = root / "feature_statistics.json"
    feature_order_ok = order_path.is_file()
    feature_stats_ok = stats_path.is_file()
    return {
        "version": version,
        "bundle_dir": str(root),
        "artifacts_present": present,
        "artifacts_missing": missing,
        "all_required_present": len(missing) == 0,
        "checksum_valid": checksum.get("valid", False),
        "checksum": checksum,
        "feature_order_ok": feature_order_ok,
        "feature_statistics_ok": feature_stats_ok,
    }


def validate_registry(*, base_dir: str | None = None, symbol: str = "XAUUSD") -> dict[str, Any]:
    registry = EngineRegistry.build_default(base_dir=base_dir, build_trend_if_missing=False, symbol=symbol)
    ids = registry.list_ids()
    active = resolve_active_trend_engine_id()
    v40 = registry.get(TREND_ENGINE_ID)
    v41 = registry.get(TREND_ENGINE_V41_ID)
    return {
        "registered_ids": ids,
        "v40_available": v40 is not None,
        "v41_available": v41 is not None,
        "active_engine_id": active,
        "active_resolvable": registry.get(active) is not None,
        "both_versions_registered": v40 is not None and v41 is not None,
        "health": registry.health_all(),
    }


def validate_prediction(
    row: pd.Series,
    *,
    base_dir: str | None = None,
    version: str = "v41",
) -> dict[str, Any]:
    bundle = load_trend_bundle(base_dir=base_dir, version=version)
    enriched = attach_top5_features(pd.DataFrame([row])).iloc[0]
    t0 = time.perf_counter()
    prob = bundle.predict_proba(enriched)
    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "version": version,
        "probability": round(float(prob), 6),
        "latency_ms": round(latency_ms, 3),
        "feature_count": len(bundle.feature_order),
        "in_range": 0.0 <= prob <= 1.0,
    }


def run_health_validation(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    sample_row: pd.Series | None = None,
) -> dict[str, Any]:
    v40_bundle = validate_bundle_artifacts(base_dir=base_dir, version="v40")
    v41_bundle = validate_bundle_artifacts(base_dir=base_dir, version="v41")
    registry = validate_registry(base_dir=base_dir, symbol=symbol)

    prediction: dict[str, Any] = {"skipped": True}
    if sample_row is not None:
        prediction = validate_prediction(sample_row, base_dir=base_dir, version="v41")

    passed = (
        v40_bundle["checksum_valid"]
        and v41_bundle["checksum_valid"]
        and v41_bundle["all_required_present"]
        and registry["both_versions_registered"]
        and registry["active_resolvable"]
    )
    return {
        "phase": "17D",
        "passed": passed,
        "v40_bundle": v40_bundle,
        "v41_bundle": v41_bundle,
        "registry": registry,
        "prediction": prediction,
        "active_engine": version_to_engine_id(resolve_active_trend_engine_id()),
    }
