"""Phase 15A — production integration preparation (no live wiring)."""

from tradingbot.ml.phase15a.config import (
    BUNDLE_VERSION,
    EXPECTED_DATASET_FINGERPRINT,
    RANGE_ENGINE_ID,
    TREND_ENGINE_ID,
)
from tradingbot.ml.phase15a.engine_discovery import discover_engines
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.health_check import run_health_checks
from tradingbot.ml.phase15a.orchestrator import Phase15AResult, run_phase15a_preparation
from tradingbot.ml.phase15a.trend_bundle import (
    TrendRfBundle,
    freeze_trend_bundle,
    load_trend_bundle,
    validate_trend_checksum,
)
from tradingbot.ml.phase15a.unified_signal import SIGNAL_SCHEMA, UnifiedSignal

__all__ = [
    "BUNDLE_VERSION",
    "EXPECTED_DATASET_FINGERPRINT",
    "RANGE_ENGINE_ID",
    "TREND_ENGINE_ID",
    "EngineRegistry",
    "Phase15AResult",
    "SIGNAL_SCHEMA",
    "TrendRfBundle",
    "UnifiedSignal",
    "discover_engines",
    "freeze_trend_bundle",
    "load_trend_bundle",
    "run_health_checks",
    "run_phase15a_preparation",
    "validate_trend_checksum",
]
