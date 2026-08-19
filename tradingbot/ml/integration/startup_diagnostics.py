"""Startup engine selection diagnostics — explicit ML vs legacy choice."""

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


def resolve_engine_selection() -> EngineSelection:
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
    vol_on = bool(get_live_config().get("VOL_REGIME_ENABLED", False))
    adaptive_on = bool(get_live_config().get("ADAPTIVE_REGIME_ENABLED", False))
    router_on = bool(get_live_config().get("MULTI_ENGINE_ROUTER_ENABLED", False))

    if not present:
        return EngineSelection(
            selected_engine="UNCONFIGURED",
            reason="USE_ML_KERNEL not set — refusing silent legacy; set USE_ML_KERNEL=1 or =0",
            config_source="environment:absent",
            ml_kernel_env_present=False,
            ml_kernel_enabled=False,
            legacy_fallback_allowed=fallback,
        )
    if enabled:
        return EngineSelection(
            selected_engine="ML_KERNEL",
            reason=f"USE_ML_KERNEL={raw!r} enables ML pipeline",
            config_source="environment:USE_ML_KERNEL",
            ml_kernel_env_present=True,
            ml_kernel_enabled=True,
            legacy_fallback_allowed=fallback,
        )
    if router_on and not enabled:
        return EngineSelection(
            selected_engine="MULTI_ENGINE_ROUTER",
            reason=f"USE_ML_KERNEL={raw!r} + MULTI_ENGINE_ROUTER_ENABLED=True",
            config_source="live:MULTI_ENGINE_ROUTER_ENABLED",
            ml_kernel_env_present=True,
            ml_kernel_enabled=False,
            legacy_fallback_allowed=fallback,
        )
    if adaptive_on and not enabled:
        return EngineSelection(
            selected_engine="ADAPTIVE_REGIME",
            reason=f"USE_ML_KERNEL={raw!r} + ADAPTIVE_REGIME_ENABLED=True",
            config_source="live:ADAPTIVE_REGIME_ENABLED",
            ml_kernel_env_present=True,
            ml_kernel_enabled=False,
            legacy_fallback_allowed=fallback,
        )
    if vol_on:
        return EngineSelection(
            selected_engine="VOL_REGIME",
            reason=f"USE_ML_KERNEL={raw!r} + VOL_REGIME_ENABLED=True",
            config_source="live:VOL_REGIME_ENABLED",
            ml_kernel_env_present=True,
            ml_kernel_enabled=False,
            legacy_fallback_allowed=fallback,
        )
    return EngineSelection(
        selected_engine="LEGACY_PRICE_ACTION",
        reason=f"USE_ML_KERNEL={raw!r} explicitly selects legacy PriceAction",
        config_source="environment:USE_ML_KERNEL",
        ml_kernel_env_present=True,
        ml_kernel_enabled=False,
        legacy_fallback_allowed=fallback,
    )


def log_engine_selection() -> EngineSelection:
    sel = resolve_engine_selection()
    if not sel.ml_kernel_env_present:
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
