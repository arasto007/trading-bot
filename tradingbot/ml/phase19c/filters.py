"""Phase 19C — configurable RSI / ADX profitability filters."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.phase19c.config import (
    ENV_ADX_MAX,
    ENV_ADX_MIN,
    ENV_ENABLE_ADX,
    ENV_ENABLE_RSI,
    ENV_RSI_MAX,
    ENV_RSI_MIN,
    _env_bool,
)


@dataclass(frozen=True)
class ProfitabilityFilterSettings:
    enable_rsi: bool = True
    enable_adx: bool = True
    rsi_min: float = 40.0
    rsi_max: float = 60.0
    adx_min: float = 15.0
    adx_max: float = 50.0

    @property
    def any_enabled(self) -> bool:
        return self.enable_rsi or self.enable_adx

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_rsi_filter": self.enable_rsi,
            "enable_adx_filter": self.enable_adx,
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "adx_min": self.adx_min,
            "adx_max": self.adx_max,
        }


@dataclass
class ProfitabilityFilterResult:
    passed: bool
    settings: ProfitabilityFilterSettings
    rsi: float | None = None
    adx: float | None = None
    blocked_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "settings": self.settings.to_dict(),
            "rsi": self.rsi,
            "adx": self.adx,
            "blocked_by": list(self.blocked_by),
        }


def load_filter_settings() -> ProfitabilityFilterSettings:
    """Load filter settings from environment (defaults: both enabled)."""
    return ProfitabilityFilterSettings(
        enable_rsi=_env_bool(ENV_ENABLE_RSI, True),
        enable_adx=_env_bool(ENV_ENABLE_ADX, True),
        rsi_min=float(os.environ.get(ENV_RSI_MIN, "40")),
        rsi_max=float(os.environ.get(ENV_RSI_MAX, "60")),
        adx_min=float(os.environ.get(ENV_ADX_MIN, "15")),
        adx_max=float(os.environ.get(ENV_ADX_MAX, "50")),
    )


def _feature_float(features: dict[str, Any], key: str, default: float) -> float:
    val = features.get(key, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def apply_profitability_filters(
    features: dict[str, Any],
    settings: ProfitabilityFilterSettings | None = None,
) -> ProfitabilityFilterResult:
    """
    Evaluate RSI mid + ADX band filters on market features.

    When all filters are disabled, always passes (Phase 19A equivalence).
    """
    cfg = settings or load_filter_settings()
    rsi = _feature_float(features, "rsi", 50.0)
    adx = _feature_float(features, "adx", 0.0)
    blocked: list[str] = []

    if not cfg.any_enabled:
        return ProfitabilityFilterResult(passed=True, settings=cfg, rsi=rsi, adx=adx)

    if cfg.enable_rsi and not (cfg.rsi_min <= rsi <= cfg.rsi_max):
        blocked.append("rsi_filter")
    if cfg.enable_adx and not (cfg.adx_min <= adx <= cfg.adx_max):
        blocked.append("adx_filter")

    return ProfitabilityFilterResult(
        passed=len(blocked) == 0,
        settings=cfg,
        rsi=rsi,
        adx=adx,
        blocked_by=blocked,
    )


def filter_settings_from_dict(data: dict[str, Any]) -> ProfitabilityFilterSettings:
    return ProfitabilityFilterSettings(
        enable_rsi=bool(data.get("enable_rsi_filter", True)),
        enable_adx=bool(data.get("enable_adx_filter", True)),
        rsi_min=float(data.get("rsi_min", 40)),
        rsi_max=float(data.get("rsi_max", 60)),
        adx_min=float(data.get("adx_min", 15)),
        adx_max=float(data.get("adx_max", 50)),
    )
