"""Phase 50A — PA production lock helpers."""

from __future__ import annotations

from typing import Any


def is_pa_production_lock(config: dict[str, Any] | None = None) -> bool:
    """True when only PA may be selected; VOL/Adaptive are log-only probes."""
    from tradingbot.config.live import get_live_config

    live = get_live_config()
    if config:
        adaptive = bool(config.get("ADAPTIVE_REGIME_ENABLED", live.get("ADAPTIVE_REGIME_ENABLED")))
        vol = bool(config.get("VOL_REGIME_ENABLED", live.get("VOL_REGIME_ENABLED")))
        lock = bool(config.get("PA_PRODUCTION_LOCK", live.get("PA_PRODUCTION_LOCK", True)))
    else:
        adaptive = bool(live.get("ADAPTIVE_REGIME_ENABLED"))
        vol = bool(live.get("VOL_REGIME_ENABLED"))
        lock = bool(live.get("PA_PRODUCTION_LOCK", True))
    return lock and not adaptive and not vol
