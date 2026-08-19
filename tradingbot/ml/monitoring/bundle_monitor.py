"""Phase 15C — frozen bundle checksum monitor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase9_9_metadata_path
from tradingbot.ml.monitoring.config import EXPECTED_DATASET_FINGERPRINT
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.phase15a.config import BUNDLE_VERSION, BUNDLE_VERSION_V41
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, trend_rf_metadata_path, validate_trend_checksum
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version


class BundleMonitor:
    """Monitor phase9_9 and active trend_rf bundle integrity."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = base_dir

    def check_trend(self) -> dict[str, Any]:
        version = resolve_bundle_version()
        engine_id = resolve_active_trend_engine_id()
        chk = validate_trend_checksum(base_dir=self._base_dir, version=version)
        meta: dict[str, Any] = {}
        meta_path = trend_rf_metadata_path(self._base_dir, version=version)
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        default_version = BUNDLE_VERSION_V41 if version == "v41" else BUNDLE_VERSION
        return {
            "engine": engine_id,
            "bundle_version": version,
            "checksum_valid": bool(chk.get("valid")),
            "bundle_sha256": chk.get("bundle_sha256"),
            "version": meta.get("version", default_version),
            "training_fingerprint": meta.get("training_fingerprint"),
            "dataset_fingerprint": meta.get("dataset_fingerprint"),
            "feature_count": len(meta.get("feature_columns", [])),
        }

    def check_phase99(self) -> dict[str, Any]:
        try:
            bundle = load_phase9_9_bundle(base_dir=self._base_dir, build_if_missing=False)
            meta_path = phase9_9_metadata_path(self._base_dir)
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
            return {
                "engine": "phase9_9",
                "checksum_valid": True,
                "version": meta.get("phase", "9.9"),
                "feature_order": bundle.feature_order,
                "dataset_fingerprint": meta.get("dataset_fingerprint"),
            }
        except Exception as exc:
            return {"engine": "phase9_9", "checksum_valid": False, "error": str(exc)}

    def check_all(self) -> dict[str, Any]:
        trend = self.check_trend()
        phase99 = self.check_phase99()
        engine_id = trend.get("engine", resolve_active_trend_engine_id())
        fp_match = (
            trend.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
            and phase99.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
        )
        all_valid = trend.get("checksum_valid") and phase99.get("checksum_valid")
        return {
            "active_trend_engine": engine_id,
            engine_id: trend,
            "phase9_9": phase99,
            "all_valid": all_valid,
            "dataset_fingerprint_match": fp_match,
            "expected_fingerprint": EXPECTED_DATASET_FINGERPRINT,
        }
