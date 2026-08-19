"""Production signal filter mode configuration."""

from __future__ import annotations

import os
from enum import Enum


class SignalFilterMode(str, Enum):
    OFF = "OFF"
    WPSQF = "WPSQF"


_VALID = {m.value for m in SignalFilterMode}
DEFAULT_THRESHOLD = 77.56


def resolve_signal_filter_mode(value: str | None = None, *, config: dict | None = None) -> SignalFilterMode:
    if value is not None:
        raw = str(value).strip().upper()
    elif config and config.get("signal_filter_mode"):
        raw = str(config["signal_filter_mode"]).strip().upper()
    else:
        raw = os.getenv("TRADINGBOT_SIGNAL_FILTER", SignalFilterMode.OFF.value).strip().upper()
    if raw in _VALID:
        return SignalFilterMode(raw)
    return SignalFilterMode.OFF


def resolve_wpsqf_threshold(value: float | None = None, *, config: dict | None = None) -> float:
    if value is not None:
        return float(value)
    if config and config.get("wpsqf_threshold") is not None:
        return float(config["wpsqf_threshold"])
    env = os.getenv("TRADINGBOT_WPSQF_THRESHOLD")
    if env:
        return float(env)
    return DEFAULT_THRESHOLD
