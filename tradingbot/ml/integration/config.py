"""Phase 10.1 — ML kernel shadow feature flags."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_ml_shadow_enabled() -> bool:
    return _env_bool("ENABLE_ML_SHADOW", False)


def is_ml_shadow_mode() -> bool:
    return _env_bool("ML_SHADOW_MODE", False)


def is_ml_kernel_env_set() -> bool:
    """True when USE_ML_KERNEL was explicitly provided in the environment."""
    return os.environ.get("USE_ML_KERNEL") is not None


def is_ml_kernel_enabled() -> bool:
    """Phase 15B — when true, TradingKernel uses ML pipeline for signal generation."""
    if not is_ml_kernel_env_set():
        return False
    return _env_bool("USE_ML_KERNEL", False)


def is_legacy_fallback_allowed() -> bool:
    """Phase 24K — when false, ML failures produce HOLD instead of legacy fallback."""
    return _env_bool("ALLOW_LEGACY_FALLBACK", False)


def ml_kernel_config_from_env() -> dict[str, Any]:
    return {
        "use_ml_kernel": is_ml_kernel_enabled(),
        "use_ml_kernel_env_set": is_ml_kernel_env_set(),
        "allow_legacy_fallback": is_legacy_fallback_allowed(),
        "enable_ml_shadow": is_ml_shadow_enabled(),
        "ml_shadow_mode": is_ml_shadow_mode(),
    }


@dataclass
class KernelShadowConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    mode: str = "replay"  # replay | live_shadow
    shadow_days: int = 30
    risk_pct: float = 0.005
    seed: int = 42
    warmup_bars: int = 80
    max_replay_bars: int = 500

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "mode": self.mode,
            "shadow_days": self.shadow_days,
            "risk_pct": self.risk_pct,
            "seed": self.seed,
            "warmup_bars": self.warmup_bars,
            "max_replay_bars": self.max_replay_bars,
            "enable_ml_shadow": is_ml_shadow_enabled(),
            "ml_shadow_mode": is_ml_shadow_mode(),
        }
