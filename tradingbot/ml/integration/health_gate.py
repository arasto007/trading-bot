"""Phase 15B — pre-decision health validation with automatic fallback triggers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import (
    normalize_ml_base_dir,
    phase9_9_feature_order_path,
    phase9_9_metadata_path,
)
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle, verify_bundle_integrity
from tradingbot.ml.phase15a.config import EXPECTED_DATASET_FINGERPRINT
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum, trend_rf_feature_order_path, trend_rf_metadata_path
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS


class KernelFallbackError(Exception):
    """Raised when ML pipeline must fall back to legacy PriceAction."""

    def __init__(self, reason: str, *, checks: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.checks = checks or {}


@dataclass
class HealthGateResult:
    passes: bool
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passes": self.passes, "checks": self.checks, "errors": self.errors}


def validate_feature_row(row: pd.Series, *, feature_order: list[str]) -> HealthGateResult:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    for col in feature_order:
        if col not in row.index:
            checks[f"feature_{col}"] = False
            errors.append(f"missing_feature:{col}")
        else:
            checks[f"feature_{col}"] = True
    return HealthGateResult(passes=not errors, checks=checks, errors=errors)


def _active_trend_feature_order(base_dir: str, *, version: str) -> list[str]:
    fo_path = trend_rf_feature_order_path(base_dir, version=version)
    if not fo_path.is_file():
        return list(TREND_ML_FEATURE_COLUMNS)
    payload = json.loads(fo_path.read_text(encoding="utf-8"))
    order = payload.get("feature_order") or payload.get("features") or []
    return [str(x) for x in order]


def run_pre_decision_health(
    *,
    registry: EngineRegistry,
    base_dir: str | None = None,
    unified_row: pd.Series | None = None,
) -> HealthGateResult:
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version

    base_dir = normalize_ml_base_dir(base_dir)
    checks: dict[str, bool] = {}
    errors: list[str] = []

    active_version = resolve_bundle_version()
    active_engine_id = resolve_active_trend_engine_id()
    checks["active_trend_engine_id"] = bool(active_engine_id)
    checks["active_bundle_version"] = active_version in ("v40", "v41")

    trend_chk = validate_trend_checksum(base_dir=base_dir, version=active_version)
    checks["trend_checksum"] = bool(trend_chk.get("valid"))
    if not checks["trend_checksum"]:
        errors.append("trend_checksum_invalid")

    p99_bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    probe = {f: 0.0 for f in p99_bundle.feature_order}
    p99 = verify_bundle_integrity(p99_bundle, probe)
    checks["phase9_checksum"] = p99.passed
    if not p99.passed:
        errors.extend(p99.errors or ["phase9_integrity_fail"])

    expected_order = _active_trend_feature_order(base_dir, version=active_version)
    fo_path = trend_rf_feature_order_path(base_dir, version=active_version)
    if fo_path.is_file() and expected_order:
        checks["trend_feature_order"] = True
    else:
        checks["trend_feature_order"] = False
        errors.append("trend_feature_order_missing")

    meta_path = trend_rf_metadata_path(base_dir, version=active_version)
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        checks["training_fingerprint"] = bool(meta.get("training_fingerprint"))
        checks["dataset_fingerprint"] = meta.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
    else:
        checks["training_fingerprint"] = False
        checks["dataset_fingerprint"] = False
        errors.append("trend_metadata_missing")

    active_engine = registry.get(active_engine_id)
    checks["active_engine_registered"] = active_engine is not None
    if active_engine is None:
        errors.append("active_trend_engine_missing")

    p99_meta = phase9_9_metadata_path(base_dir)
    if p99_meta.is_file():
        p99m = json.loads(p99_meta.read_text(encoding="utf-8"))
        checks["phase9_fingerprint"] = p99m.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
    else:
        checks["phase9_fingerprint"] = False

    p99_fo = phase9_9_feature_order_path(base_dir)
    checks["phase9_feature_order_file"] = p99_fo.is_file()
    if not checks["phase9_feature_order_file"]:
        errors.append("phase9_feature_order_missing")

    reg_health = registry.health_all()
    checks["registry_health"] = all(
        h.get("status") in ("OK", "FAIL") for h in reg_health.values()
    ) and all(h.get("status") == "OK" for h in reg_health.values())
    if not checks["registry_health"]:
        errors.append("registry_health_fail")

    if unified_row is not None and expected_order:
        feat = validate_feature_row(unified_row, feature_order=expected_order)
        checks.update(feat.checks)
        errors.extend(feat.errors)

    return HealthGateResult(passes=not errors, checks=checks, errors=errors)


def require_health(**kwargs: Any) -> HealthGateResult:
    result = run_pre_decision_health(**kwargs)
    if not result.passes:
        raise KernelFallbackError(
            ";".join(result.errors) or "health_check_failed",
            checks=result.to_dict(),
        )
    return result
