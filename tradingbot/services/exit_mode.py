"""Production exit mode configuration."""

from __future__ import annotations

import os
from enum import Enum


class ExitMode(str, Enum):
    CURRENT = "CURRENT"
    HYBRID_B = "HYBRID_B"


_VALID = {m.value for m in ExitMode}


def resolve_exit_mode(value: str | None = None, *, config: dict | None = None) -> ExitMode:
    """Resolve exit mode from explicit value, config dict, or TRADINGBOT_EXIT_MODE env."""
    if value is not None:
        raw = str(value).strip().upper()
    elif config and config.get("exit_mode"):
        raw = str(config["exit_mode"]).strip().upper()
    else:
        raw = os.getenv("TRADINGBOT_EXIT_MODE", ExitMode.CURRENT.value).strip().upper()
    if raw in ("CURRENT", "CURRENT_TP_SL", "TP_SL"):
        return ExitMode.CURRENT
    if raw in ("HYBRID_B", "HYBRIDB"):
        return ExitMode.HYBRID_B
    if raw in _VALID:
        return ExitMode(raw)
    return ExitMode.CURRENT
