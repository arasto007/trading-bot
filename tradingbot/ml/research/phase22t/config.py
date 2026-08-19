"""Phase 22T — research feature flag for live Phase99 feature source."""

from __future__ import annotations

import os

ENV_FLAG = "RESEARCH_USE_LIVE_PHASE99_FEATURES"
PHASE99_FEATURES = ("structure_distance", "ema50_slope", "candle_direction")
SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
DATASET_LABEL = "A"
VERDICT_EFFECT_THRESHOLD_PCT = 5.0


def use_live_phase99_features() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def set_live_phase99_features(enabled: bool) -> None:
    os.environ[ENV_FLAG] = "true" if enabled else "false"
