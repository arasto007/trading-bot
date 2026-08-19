"""Phase 18C — model / bundle validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.phase15a.config import trend_rf_bundle_root
from tradingbot.ml.phase15a.trend_bundle import load_trend_bundle, validate_trend_checksum


def _bundle_files(version: str, base_dir: str | None) -> dict[str, bool]:
    root = trend_rf_bundle_root(base_dir, version=version)
    names = (
        "model.pkl", "scaler.pkl", "feature_order.json", "metadata.json",
        "config.json",
    )
    extra = ("checksum.json", "checksum.sha256")
    present = {n: (root / n).is_file() for n in names}
    present["checksum"] = any((root / n).is_file() for n in extra)
    if version == "v41":
        for n in ("feature_statistics.json", "version.json", "training_manifest.json"):
            present[n] = (root / n).is_file()
    return present


def validate_bundles(*, base_dir: str | None = None) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}

    for ver, label in (("v40", "trend_rf_v40"), ("v41", "trend_rf_v41")):
        chk = validate_trend_checksum(base_dir=base_dir, version=ver)
        files = _bundle_files(ver, base_dir)
        try:
            bundle = load_trend_bundle(base_dir=base_dir, version=ver, build_if_missing=False)
            meta = bundle.metadata or {}
            items[label] = {
                "status": "PASS" if chk.get("valid") and all(files.values()) else "FAIL",
                "checksum_valid": chk.get("valid"),
                "checksum": chk,
                "files": files,
                "feature_order": list(bundle.feature_order),
                "feature_count": len(bundle.feature_order),
                "version": meta.get("version") or bundle.version,
                "scaler_present": bundle.scaler is not None,
                "model_present": bundle.model is not None,
                "metadata_keys": sorted(meta.keys()),
            }
        except Exception as exc:  # noqa: BLE001
            items[label] = {"status": "FAIL", "error": str(exc), "checksum": chk, "files": files}

    try:
        p99 = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        items["phase9_9"] = {
            "status": "PASS" if p99 is not None else "FAIL",
            "feature_order": list(p99.feature_order) if p99 else [],
            "feature_count": len(p99.feature_order) if p99 else 0,
            "scaler_present": p99.scaler is not None if p99 else False,
            "model_present": p99.model is not None if p99 else False,
        }
    except Exception as exc:  # noqa: BLE001
        items["phase9_9"] = {"status": "FAIL", "error": str(exc)}

    statuses = [v["status"] for v in items.values()]
    return {
        "phase": "18C",
        "passed": all(s == "PASS" for s in statuses),
        "items": items,
        "summary": {
            "pass": sum(1 for s in statuses if s == "PASS"),
            "fail": sum(1 for s in statuses if s == "FAIL"),
        },
    }
