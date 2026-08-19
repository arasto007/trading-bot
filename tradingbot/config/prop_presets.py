"""Prop-firm risk presets (local — no VPS required)."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "ftmo": {
        "PROP_FIRM_NAME": "FTMO-style",
        "MAX_DAILY_RISK": 0.05,
        "MAX_TRADES_PER_DAY": 5,
        "MAX_CONSECUTIVE_LOSSES": 3,
        "RISK_PER_TRADE": 0.01,
        "MAX_LOT_SIZE": 0.05,
        "VOL_REGIME_MAX_LOT": 0.01,
        "VOL_REGIME_MAX_CONCURRENT": 1,
        "VOL_REGIME_DAILY_KILL_SWITCH_PCT": 4.0,
        "EMERGENCY_STOP_CONDITIONS": {
            "max_drawdown": 0.10,
            "max_consecutive_losses": 3,
            "max_daily_loss": 0.05,
        },
        "KILL_SWITCH_DD_BUFFER": 0.90,
    },
    "conservative": {
        "PROP_FIRM_NAME": "Conservative",
        "MAX_DAILY_RISK": 0.03,
        "MAX_TRADES_PER_DAY": 3,
        "MAX_CONSECUTIVE_LOSSES": 2,
        "RISK_PER_TRADE": 0.005,
        "MAX_LOT_SIZE": 0.02,
        "VOL_REGIME_MAX_LOT": 0.01,
        "EMERGENCY_STOP_CONDITIONS": {
            "max_drawdown": 0.08,
            "max_consecutive_losses": 2,
            "max_daily_loss": 0.03,
        },
    },
}


def active_preset_name() -> str:
    return (
        os.getenv("TRADINGBOT_PROP_PRESET", "").strip().lower()
        or os.getenv("PROP_FIRM_PRESET", "").strip().lower()
        or "none"
    )


def apply_prop_preset(config: dict[str, Any]) -> dict[str, Any]:
    name = active_preset_name()
    if not name or name == "none":
        return config
    preset = PRESETS.get(name)
    if not preset:
        return config
    out = deepcopy(config)
    for key, value in preset.items():
        if key == "EMERGENCY_STOP_CONDITIONS" and isinstance(value, dict):
            base = dict(out.get("EMERGENCY_STOP_CONDITIONS") or {})
            base.update(value)
            out["EMERGENCY_STOP_CONDITIONS"] = base
        else:
            out[key] = value
    out["PROP_FIRM_PRESET"] = name
    return out
