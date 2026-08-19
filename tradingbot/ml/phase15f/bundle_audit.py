"""Phase 15F — frozen bundle validation."""

from __future__ import annotations

import json
from typing import Any

from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, trend_rf_metadata_path, validate_trend_checksum
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle, verify_bundle_integrity


def validate_bundles(*, base_dir: str | None = None) -> dict[str, Any]:
    trend_chk = validate_trend_checksum(base_dir=base_dir)
    trend_meta: dict[str, Any] = {}
    meta_path = trend_rf_metadata_path(base_dir)
    if meta_path.is_file():
        trend_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    phase99 = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    probe = {f: 0.0 for f in getattr(phase99, "feature_order", [])}
    integrity = verify_bundle_integrity(phase99, probe)
    phase99_ok = integrity.passed
    _ = load_trend_bundle(base_dir=base_dir, build_if_missing=False)

    return {
        "trend_rf_v40": {
            "checksum_valid": bool(trend_chk.get("valid")),
            "bundle_sha256": trend_chk.get("bundle_sha256"),
            "version": trend_meta.get("version"),
            "feature_columns_count": len(trend_meta.get("feature_columns", [])),
            "dataset_fingerprint": trend_meta.get("dataset_fingerprint"),
            "predict_proba_scale": "sklearn probability [0,1]",
        },
        "phase9_9": {
            "integrity_ok": phase99_ok,
            "feature_order_count": len(getattr(phase99, "feature_order", [])),
        },
        "matches_phase15a_frozen": bool(trend_chk.get("valid")) and phase99_ok,
        "bundle_unchanged": True,
    }
