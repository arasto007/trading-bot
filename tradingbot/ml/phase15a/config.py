"""Phase 15A — configuration and paths."""

from __future__ import annotations

import json
from pathlib import Path

TREND_ENGINE_ID = "trend_rf_v40"
TREND_ENGINE_V41_ID = "trend_rf_v41"
RANGE_ENGINE_ID = "phase9_9"
EXPECTED_DATASET_FINGERPRINT = "70b38325ee1c7e1e"
DEFAULT_SEED = 42
BUNDLE_VERSION = "trend_rf_v40.1"
BUNDLE_VERSION_V41 = "trend_rf_v41"

TREND_BUNDLE_DIRS = {
    "v40": "trend_rf_bundle",
    "v41": "trend_rf_bundle_v41",
}


def phase15a_reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir

    return reports_dir(base_dir) / "phase15a"


def phase15a_final_report_path(base_dir: str | Path | None = None) -> Path:
    return phase15a_reports_dir(base_dir) / "phase15a_final_report.json"


def trend_rf_bundle_root(
    base_dir: str | Path | None = None,
    *,
    version: str = "v40",
) -> Path:
    from tradingbot.ml.data.paths import ml_root

    subdir = TREND_BUNDLE_DIRS.get(version, TREND_BUNDLE_DIRS["v40"])
    return ml_root(base_dir) / "research" / subdir


def trend_rf_model_path(base_dir: str | Path | None = None, *, version: str = "v40") -> Path:
    return trend_rf_bundle_root(base_dir, version=version) / "model.pkl"


def trend_rf_scaler_path(base_dir: str | Path | None = None, *, version: str = "v40") -> Path:
    return trend_rf_bundle_root(base_dir, version=version) / "scaler.pkl"


def trend_rf_feature_order_path(base_dir: str | Path | None = None, *, version: str = "v40") -> Path:
    return trend_rf_bundle_root(base_dir, version=version) / "feature_order.json"


def trend_rf_metadata_path(base_dir: str | Path | None = None, *, version: str = "v40") -> Path:
    return trend_rf_bundle_root(base_dir, version=version) / "metadata.json"


def trend_rf_config_path(base_dir: str | Path | None = None, *, version: str = "v40") -> Path:
    return trend_rf_bundle_root(base_dir, version=version) / "config.json"


def trend_rf_checksum_path(base_dir: str | Path | None = None, *, version: str = "v40") -> Path:
    root = trend_rf_bundle_root(base_dir, version=version)
    sha_path = root / "checksum.sha256"
    if sha_path.is_file():
        return sha_path
    return root / "checksum.json"


def load_engine_manifests_dir(base_dir: str | Path | None = None) -> Path:
    return trend_rf_bundle_root(base_dir).parent / "engine_manifests"


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
