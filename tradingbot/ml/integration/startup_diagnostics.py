"""Startup engine selection diagnostics — effective registry, not raw env only."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EngineSelection:
    selected_engine: str
    reason: str
    config_source: str
    ml_kernel_env_present: bool
    ml_kernel_enabled: bool
    legacy_fallback_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_engine": self.selected_engine,
            "reason": self.reason,
            "config_source": self.config_source,
            "ml_kernel_env_present": self.ml_kernel_env_present,
            "ml_kernel_enabled": self.ml_kernel_enabled,
            "legacy_fallback_allowed": self.legacy_fallback_allowed,
        }


def _ml_effective_after_gate(enabled: bool) -> bool:
    """Same gate downgrade as factory.build_strategy_registry — no registries built."""
    if not enabled:
        return False
    from tradingbot.ml.shadow.shadow_gate import evaluate_ml_live_gate

    return bool(evaluate_ml_live_gate().get("allowed"))


def resolve_engine_selection() -> EngineSelection:
    """Describe the registry factory would build. Does not instantiate strategies."""
    from tradingbot.config.live import get_live_config
    from tradingbot.ml.integration.config import (
        is_legacy_fallback_allowed,
        is_ml_kernel_enabled,
        is_ml_kernel_env_set,
    )

    raw = os.environ.get("USE_ML_KERNEL")
    present = is_ml_kernel_env_set()
    enabled = is_ml_kernel_enabled()
    fallback = is_legacy_fallback_allowed()
    live_cfg = get_live_config()
    vol_on = bool(live_cfg.get("VOL_REGIME_ENABLED", False))
    adaptive_on = bool(live_cfg.get("ADAPTIVE_REGIME_ENABLED", False))
    router_on = bool(live_cfg.get("MULTI_ENGINE_ROUTER_ENABLED", False))
    ml_effective = _ml_effective_after_gate(enabled)

    # Branch order mirrors factory.py — do not instantiate registries.
    if router_on and not ml_effective:
        if not present:
            reason = "USE_ML_KERNEL absent; MULTI_ENGINE_ROUTER_ENABLED selects router"
        elif enabled and not ml_effective:
            reason = f"USE_ML_KERNEL={raw!r} blocked by ML live gate; router remains selected"
        else:
            reason = f"USE_ML_KERNEL={raw!r} + MULTI_ENGINE_ROUTER_ENABLED=True"
        return EngineSelection(
            selected_engine="MULTI_ENGINE_ROUTER",
            reason=reason,
            config_source="live:MULTI_ENGINE_ROUTER_ENABLED",
            ml_kernel_env_present=present,
            ml_kernel_enabled=enabled,
            legacy_fallback_allowed=fallback,
        )
    if adaptive_on and not ml_effective:
        return EngineSelection(
            selected_engine="ADAPTIVE_REGIME",
            reason=f"USE_ML_KERNEL={raw!r} + ADAPTIVE_REGIME_ENABLED=True",
            config_source="live:ADAPTIVE_REGIME_ENABLED",
            ml_kernel_env_present=present,
            ml_kernel_enabled=enabled,
            legacy_fallback_allowed=fallback,
        )
    if vol_on and not ml_effective:
        return EngineSelection(
            selected_engine="VOL_REGIME",
            reason=f"USE_ML_KERNEL={raw!r} + VOL_REGIME_ENABLED=True",
            config_source="live:VOL_REGIME_ENABLED",
            ml_kernel_env_present=present,
            ml_kernel_enabled=enabled,
            legacy_fallback_allowed=fallback,
        )
    if ml_effective:
        return EngineSelection(
            selected_engine="ML_KERNEL",
            reason=f"USE_ML_KERNEL={raw!r} and ML live gate allowed",
            config_source="environment:USE_ML_KERNEL",
            ml_kernel_env_present=True,
            ml_kernel_enabled=True,
            legacy_fallback_allowed=fallback,
        )
    if not present and not vol_on:
        return EngineSelection(
            selected_engine="UNCONFIGURED",
            reason="USE_ML_KERNEL not set — refusing silent legacy; set USE_ML_KERNEL=1 or =0",
            config_source="environment:absent",
            ml_kernel_env_present=False,
            ml_kernel_enabled=False,
            legacy_fallback_allowed=fallback,
        )
    return EngineSelection(
        selected_engine="LEGACY_PRICE_ACTION",
        reason=f"USE_ML_KERNEL={raw!r} explicitly selects legacy PriceAction",
        config_source="environment:USE_ML_KERNEL",
        ml_kernel_env_present=present,
        ml_kernel_enabled=False,
        legacy_fallback_allowed=fallback,
    )


def log_engine_selection() -> EngineSelection:
    sel = resolve_engine_selection()
    if sel.selected_engine == "UNCONFIGURED":
        logger.warning(
            "ENGINE SELECTION | %s | reason=%s | source=%s",
            sel.selected_engine,
            sel.reason,
            sel.config_source,
        )
    else:
        logger.info(
            "ENGINE SELECTION | %s | reason=%s | source=%s | legacy_fallback=%s",
            sel.selected_engine,
            sel.reason,
            sel.config_source,
            sel.legacy_fallback_allowed,
        )
    return sel
