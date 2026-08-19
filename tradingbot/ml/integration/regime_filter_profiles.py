"""Phase 23G — regime-conditional profitability filter profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID
from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings, load_filter_settings
from tradingbot.ml.research.phase22c.config import load_phase22c_config

ENV_ENABLE_RANGE_FILTER_PROFILE = "ENABLE_RANGE_FILTER_PROFILE"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def range_filter_profile_enabled() -> bool:
    """Single rollback switch — FALSE restores Phase22C filter behavior for all regimes."""
    return _env_bool(ENV_ENABLE_RANGE_FILTER_PROFILE, True)


@dataclass(frozen=True)
class RangeFilterProfile:
    """Phase 23E/23F approved profile — RANGE + phase9_9 only."""

    enable_rsi: bool = True
    enable_adx: bool = True
    rsi_min: float = 40.0
    rsi_max: float = 65.0
    adx_min: float = 15.0
    adx_max: float = 40.0
    profile_id: str = "range_phase23e"
    scope: str = "RANGE + phase9_9 only"

    def to_settings(self, *, base: ProfitabilityFilterSettings | None = None) -> ProfitabilityFilterSettings:
        src = base or load_filter_settings()
        return ProfitabilityFilterSettings(
            enable_rsi=src.enable_rsi if base is not None else self.enable_rsi,
            enable_adx=src.enable_adx if base is not None else self.enable_adx,
            rsi_min=self.rsi_min,
            rsi_max=self.rsi_max,
            adx_min=self.adx_min,
            adx_max=self.adx_max,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": self.scope,
            **self.to_settings().to_dict(),
        }


@dataclass(frozen=True)
class TrendFilterProfile:
    """Phase 22C production profile for TREND regime."""

    enable_rsi: bool = True
    enable_adx: bool = True
    rsi_min: float = 35.0
    rsi_max: float = 65.0
    adx_min: float = 10.0
    adx_max: float = 55.0
    profile_id: str = "trend_phase22c"
    scope: str = "TREND"

    @classmethod
    def from_phase22c(
        cls,
        cfg22,
        base: ProfitabilityFilterSettings | None = None,
    ) -> TrendFilterProfile:
        src = base or load_filter_settings()
        return cls(
            enable_rsi=src.enable_rsi,
            enable_adx=src.enable_adx,
            rsi_min=cfg22.rsi_min,
            rsi_max=cfg22.rsi_max,
            adx_min=cfg22.adx_min,
            adx_max=cfg22.adx_max,
        )

    def to_settings(self) -> ProfitabilityFilterSettings:
        return ProfitabilityFilterSettings(
            enable_rsi=self.enable_rsi,
            enable_adx=self.enable_adx,
            rsi_min=self.rsi_min,
            rsi_max=self.rsi_max,
            adx_min=self.adx_min,
            adx_max=self.adx_max,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": self.scope,
            **self.to_settings().to_dict(),
        }


@dataclass(frozen=True)
class TransitionFilterProfile:
    """Phase 22C production profile for TRANSITION / recovery / fallback paths."""

    enable_rsi: bool = True
    enable_adx: bool = True
    rsi_min: float = 35.0
    rsi_max: float = 65.0
    adx_min: float = 10.0
    adx_max: float = 55.0
    profile_id: str = "transition_phase22c"
    scope: str = "TRANSITION + recovery + fallback"

    @classmethod
    def from_phase22c(
        cls,
        cfg22,
        base: ProfitabilityFilterSettings | None = None,
    ) -> TransitionFilterProfile:
        src = base or load_filter_settings()
        return cls(
            enable_rsi=src.enable_rsi,
            enable_adx=src.enable_adx,
            rsi_min=cfg22.rsi_min,
            rsi_max=cfg22.rsi_max,
            adx_min=cfg22.adx_min,
            adx_max=cfg22.adx_max,
        )

    def to_settings(self) -> ProfitabilityFilterSettings:
        return ProfitabilityFilterSettings(
            enable_rsi=self.enable_rsi,
            enable_adx=self.enable_adx,
            rsi_min=self.rsi_min,
            rsi_max=self.rsi_max,
            adx_min=self.adx_min,
            adx_max=self.adx_max,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": self.scope,
            **self.to_settings().to_dict(),
        }


@dataclass
class FilterProfileDiagnostics:
    profile_used: str
    regime: str
    engine: str | None
    rsi_limits: tuple[float, float] | None
    adx_limits: tuple[float, float] | None
    enable_range_filter_profile: bool
    filter_reason: str | None = None
    blocked_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_used": self.profile_used,
            "regime": self.regime,
            "engine": self.engine,
            "rsi_limits": list(self.rsi_limits) if self.rsi_limits else None,
            "adx_limits": list(self.adx_limits) if self.adx_limits else None,
            "enable_range_filter_profile": self.enable_range_filter_profile,
            "filter_reason": self.filter_reason,
            "blocked_by": list(self.blocked_by),
        }


def phase22c_filter_settings() -> ProfitabilityFilterSettings:
    """Legacy unified Phase22C settings (rollback / pre-23G behavior)."""
    cfg22 = load_phase22c_config()
    base = load_filter_settings()
    if not cfg22.enabled:
        return base
    return TrendFilterProfile.from_phase22c(cfg22, base).to_settings()


def select_profitability_filter_settings(
    *,
    regime: str,
    engine: str | None,
) -> tuple[ProfitabilityFilterSettings | None, FilterProfileDiagnostics]:
    """
    Resolve profitability filter settings from regime + active engine.

    RANGE profile applies only when ENABLE_RANGE_FILTER_PROFILE is true,
    regime is RANGE, and engine is phase9_9.
    """
    cfg22 = load_phase22c_config()
    regime_u = str(regime).upper()
    engine_id = str(engine or "")
    enabled_flag = range_filter_profile_enabled()

    if not cfg22.enabled:
        settings = load_filter_settings()
        return None if not settings.any_enabled else settings, FilterProfileDiagnostics(
            profile_used="env_defaults",
            regime=regime_u,
            engine=engine_id or None,
            rsi_limits=(settings.rsi_min, settings.rsi_max),
            adx_limits=(settings.adx_min, settings.adx_max),
            enable_range_filter_profile=enabled_flag,
        )

    base = load_filter_settings()

    if not enabled_flag:
        trend = TrendFilterProfile.from_phase22c(cfg22, base)
        settings = trend.to_settings()
        return settings, FilterProfileDiagnostics(
            profile_used=trend.profile_id,
            regime=regime_u,
            engine=engine_id or None,
            rsi_limits=(settings.rsi_min, settings.rsi_max),
            adx_limits=(settings.adx_min, settings.adx_max),
            enable_range_filter_profile=enabled_flag,
        )

    use_range_profile = (
        regime_u == "RANGE"
        and engine_id == RANGE_MODEL_ID
    )

    if use_range_profile:
        profile = RangeFilterProfile()
        settings = profile.to_settings(base=base)
        profile_name = profile.profile_id
    elif regime_u == "TREND":
        trend = TrendFilterProfile.from_phase22c(cfg22, base)
        settings = trend.to_settings()
        profile_name = trend.profile_id
    else:
        transition = TransitionFilterProfile.from_phase22c(cfg22, base)
        settings = transition.to_settings()
        profile_name = transition.profile_id

    return settings, FilterProfileDiagnostics(
        profile_used=profile_name,
        regime=regime_u,
        engine=engine_id or None,
        rsi_limits=(settings.rsi_min, settings.rsi_max),
        adx_limits=(settings.adx_min, settings.adx_max),
        enable_range_filter_profile=enabled_flag,
    )


def attach_filter_diagnostics(
    diagnostics: FilterProfileDiagnostics,
    filt_result,
) -> FilterProfileDiagnostics:
    if filt_result is None:
        return diagnostics
    blocked = list(getattr(filt_result, "blocked_by", []) or [])
    reason = None
    if blocked:
        reason = ",".join(blocked)
    diagnostics.blocked_by = blocked
    diagnostics.filter_reason = reason
    return diagnostics
