"""Phase 15A — model and bundle health validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase9_9_feature_order_path, phase9_9_metadata_path, phase9_9_model_path
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.phase15a.config import (
    EXPECTED_DATASET_FINGERPRINT,
    TREND_ENGINE_ID,
    RANGE_ENGINE_ID,
    trend_rf_checksum_path,
    trend_rf_feature_order_path,
    trend_rf_metadata_path,
    trend_rf_model_path,
)
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, sha256_file, validate_trend_checksum
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS


def _check_phase99_health(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    model_path = phase9_9_model_path(base_dir)
    checks["model_exists"] = model_path.is_file()
    if not checks["model_exists"]:
        errors.append("phase9_9 model missing")
    try:
        bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        checks["bundle_loads"] = True
        checks["feature_order"] = len(bundle.feature_order) == 3
        meta_path = phase9_9_metadata_path(base_dir)
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            checks["dataset_fingerprint"] = meta.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
        else:
            checks["dataset_fingerprint"] = False
    except Exception as exc:
        checks["bundle_loads"] = False
        errors.append(str(exc))
    if model_path.is_file():
        checks["checksum_recorded"] = sha256_file(model_path) is not None
    return {"engine": RANGE_ENGINE_ID, "checks": checks, "errors": errors, "passes": all(checks.values()) and not errors}


def _check_trend_health(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    chk = validate_trend_checksum(base_dir=base_dir)
    checks["checksum_valid"] = bool(chk.get("valid"))
    if not checks["checksum_valid"]:
        errors.append(chk.get("reason", "checksum_invalid"))
    try:
        bundle = load_trend_bundle(base_dir=base_dir, build_if_missing=False)
        checks["bundle_loads"] = True
        checks["version_present"] = bool(bundle.version)
        checks["training_fingerprint"] = bool(bundle.metadata.get("training_fingerprint"))
        expected = list(TREND_ML_FEATURE_COLUMNS)
        checks["feature_order_match"] = bundle.feature_order == expected or set(bundle.feature_order) == set(expected)
        fo_path = trend_rf_feature_order_path(base_dir)
        checks["feature_order_file"] = fo_path.is_file()
        meta_path = trend_rf_metadata_path(base_dir)
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            checks["dataset_fingerprint"] = meta.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
        else:
            checks["dataset_fingerprint"] = False
        checks["bundle_integrity"] = trend_rf_checksum_path(base_dir).is_file() and trend_rf_model_path(base_dir).is_file()
    except Exception as exc:
        checks["bundle_loads"] = False
        errors.append(str(exc))
    return {"engine": TREND_ENGINE_ID, "checks": checks, "errors": errors, "passes": all(checks.values()) and not errors}


def run_health_checks(*, base_dir: str | Path | None = None, registry: EngineRegistry | None = None) -> dict[str, Any]:
    phase99 = _check_phase99_health(base_dir=base_dir)
    trend = _check_trend_health(base_dir=base_dir)
    reg = registry or EngineRegistry.build_default(base_dir=base_dir, build_trend_if_missing=False)
    registry_health = reg.health_all()
    all_pass = phase99["passes"] and trend["passes"]
    return {
        "phase": "15A",
        "status": "PASS" if all_pass else "NEEDS_REVIEW",
        "phase9_9": phase99,
        "trend_rf_v40": trend,
        "registry": registry_health,
        "passes": all_pass,
    }
