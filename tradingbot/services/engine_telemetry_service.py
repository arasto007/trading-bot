"""Compatibility alias -- EngineTelemetryService lives in engine_telemetry.py."""

from __future__ import annotations

from tradingbot.services.engine_telemetry import (
    ENGINE_ADAPTIVE,
    ENGINE_ML,
    ENGINE_PA,
    ENGINE_VOL,
    EngineTelemetryService,
    get_engine_telemetry,
    init_engine_log_structure,
)

__all__ = [
    "ENGINE_ADAPTIVE",
    "ENGINE_ML",
    "ENGINE_PA",
    "ENGINE_VOL",
    "EngineTelemetryService",
    "get_engine_telemetry",
    "init_engine_log_structure",
]
