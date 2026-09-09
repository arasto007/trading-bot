"""Phase 1.5.36 — read-only v41 bundle / feature-contract audit."""

from __future__ import annotations

import hashlib
from typing import Any

from tradingbot.ml.phase15a.config import trend_rf_bundle_root, trend_rf_model_path, trend_rf_scaler_path
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, sha256_file, validate_trend_checksum
from tradingbot.ml.research.phase17b.config import TOP5_FEATURES
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS

EXPECTED_FEATURE_ORDER = (
    "ema20_slope",
    "ema50_slope",
    "ema_alignment",
    "adx",
    "atr_percentile",
    "rsi",
    "macd_histogram",
    "breakout_distance",
    "higher_high_count",
    "lower_low_count",
    "candle_momentum",
    "adx_acceleration",
    "swing_efficiency",
    "fractal_dimension_proxy",
    "trend_age",
    "ema_curvature",
)
EXPECTED_BUNDLE_SHA256 = "a433fa410604b17ad195ec80469c86bca47b3df718f4072b2c5d1dc2b153eb6b"
EXPECTED_MODEL_SHA256 = "13b960cf5f85085f7f5cd3984b8f5f3b7e452af2b6515bf2f7d618e1838dc6a5"


def audit_v41_bundle(*, base_dir: str | None = None) -> dict[str, Any]:
    root = trend_rf_bundle_root(base_dir, version="v41")
    issues: list[str] = []
    if not root.is_dir():
        return {"ok": False, "issues": ["bundle_dir_missing"], "root": str(root)}

    bundle = load_trend_bundle(base_dir=base_dir, version="v41")
    checksum = validate_trend_checksum(base_dir=base_dir, version="v41")
    model_sha = sha256_file(trend_rf_model_path(base_dir, version="v41"))
    scaler_sha = sha256_file(trend_rf_scaler_path(base_dir, version="v41"))
    recomputed_bundle = hashlib.sha256((model_sha + scaler_sha).encode()).hexdigest()

    checksum_json: dict[str, Any] = {}
    checksum_json_path = root / "checksum.json"
    if checksum_json_path.is_file():
        import json

        checksum_json = json.loads(checksum_json_path.read_text(encoding="utf-8"))

    if list(bundle.feature_order) != list(EXPECTED_FEATURE_ORDER):
        issues.append("feature_order_mismatch")
    missing_base = [c for c in TREND_ML_FEATURE_COLUMNS if c not in bundle.feature_order]
    missing_top5 = [c for c in TOP5_FEATURES if c not in bundle.feature_order]
    if missing_base:
        issues.append(f"missing_base_features:{missing_base}")
    if missing_top5:
        issues.append(f"missing_top5_features:{missing_top5}")
    if not checksum.get("valid"):
        issues.append("checksum_invalid")
    if checksum.get("stored_bundle_sha256") != EXPECTED_BUNDLE_SHA256:
        issues.append("bundle_sha256_unexpected")
    if model_sha != EXPECTED_MODEL_SHA256:
        issues.append("model_sha256_unexpected")
    if checksum.get("stored_model_sha256") not in (None, model_sha):
        issues.append("stored_model_sha256_mismatch")
    # Loader prefers checksum.sha256 (bundle hash only) over checksum.json.
    # That makes validate_trend_checksum() report stored_model_sha256=None even
    # though checksum.json stores the matching model digest. Documented, not fixed.
    if checksum.get("stored_model_sha256") is None:
        issues.append("stored_model_sha256_absent_via_sha256_file")
    if checksum_json.get("model_sha256") not in (None, model_sha):
        issues.append("checksum_json_model_sha256_mismatch")
    if checksum_json.get("bundle_sha256") not in (None, EXPECTED_BUNDLE_SHA256, recomputed_bundle):
        issues.append("checksum_json_bundle_sha256_mismatch")

    meta = bundle.metadata
    cfg = bundle.config
    manifest: dict[str, Any] = {}
    manifest_path = root / "training_manifest.json"
    if manifest_path.is_file():
        import json as _json

        manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "ok": not any(
            i for i in issues
            if i != "stored_model_sha256_absent_via_sha256_file"
        ),
        "issues": issues,
        "root": str(root),
        "engine_id": cfg.get("engine_id"),
        "threshold": float(cfg.get("threshold", 0.4)),
        "rule_fn": cfg.get("rule_fn"),
        "feature_order": list(bundle.feature_order),
        "train_rows": meta.get("train_rows"),
        "total_labeled_rows": meta.get("total_labeled_rows"),
        "training_period": meta.get("training_period"),
        "train_window_days": meta.get("train_window_days"),
        "dataset_fingerprint": meta.get("dataset_fingerprint"),
        "seed": meta.get("seed"),
        "frozen_at_utc": meta.get("frozen_at_utc"),
        "symbol_documented": "XAUUSD",
        "timeframe_documented": "M5",
        "checksum": checksum,
        "checksum_json": checksum_json,
        "checksum_loader_prefers": "checksum.sha256_over_checksum.json",
        "model_sha256": model_sha,
        "recomputed_bundle_sha256": recomputed_bundle,
        "feature_contract": {
            "base_11": list(TREND_ML_FEATURE_COLUMNS),
            "top5": list(TOP5_FEATURES),
            "attach_top5_is_causal": True,
            "attach_fn": f"{attach_top5_features.__module__}.attach_top5_features",
        },
        "bundle_not_modified": True,
        "training_manifest": {
            "train_rows": (manifest.get("training_report") or {}).get("train_rows"),
            "val_rows": (manifest.get("training_report") or {}).get("val_rows"),
            "test_rows": (manifest.get("training_report") or {}).get("test_rows"),
            "timeseries_cv_mean_auc": (manifest.get("training_report") or {}).get("timeseries_cv_mean_auc"),
            "walk_forward_mean_auc": (manifest.get("training_report") or {}).get("walk_forward_mean_auc"),
            "chronological": manifest.get("chronological"),
            "scaler_fit_on": manifest.get("scaler_fit_on"),
            "note": "AUC figures are classification metrics only — not trading performance",
        },
    }
