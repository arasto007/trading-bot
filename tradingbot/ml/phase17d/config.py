"""Phase 17D — bundle promotion configuration."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = "M5"
DEFAULT_SEED = 42
DEFAULT_STRIDE = 5
DEFAULT_WARMUP = 350
REPLAY_DAYS = 365

TREND_VERSION_ENV = "TREND_MODEL_VERSION"
DEFAULT_ACTIVE_VERSION = "v41"
ROLLBACK_VERSION = "v40"

VERDICTS = (
    "DEPLOYMENT_BLOCKED",
    "READY_FOR_LIVE_SHADOW",
)

BUNDLE_ARTIFACTS = (
    "bundle.pkl",
    "model.pkl",
    "scaler.pkl",
    "feature_order.json",
    "feature_statistics.json",
    "metadata.json",
    "training_manifest.json",
    "checksum.sha256",
    "version.json",
    "config.json",
)


def reports_dir(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.data.paths import reports_dir as _r

    return _r(base_dir) / "phase17d"


def bundle_root(base_dir: str | Path | None = None) -> Path:
    from tradingbot.ml.phase15a.config import trend_rf_bundle_root

    return trend_rf_bundle_root(base_dir, version="v41")


def read_trend_model_version() -> str:
    raw = os.environ.get(TREND_VERSION_ENV, DEFAULT_ACTIVE_VERSION).strip().lower()
    if raw in ("v40", "40", "trend_rf_v40"):
        return "v40"
    if raw in ("v41", "41", "trend_rf_v41"):
        return "v41"
    return DEFAULT_ACTIVE_VERSION
