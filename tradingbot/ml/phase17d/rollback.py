"""Phase 17D — one-switch rollback validation."""

from __future__ import annotations

import os
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase17d.versioning import (
    resolve_active_trend_engine_id,
    resolve_bundle_version,
    rollback_instructions,
)


def _with_env(version: str, fn) -> Any:
    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = version
    PipelineCache.reset()
    try:
        return fn()
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev


def validate_rollback_switch(*, base_dir: str | None = None, symbol: str = "XAUUSD") -> dict[str, Any]:
    """Verify TREND_MODEL_VERSION=v40|v41 switches active engine without code changes."""

    def _probe() -> dict[str, Any]:
        registry = EngineRegistry.build_default(
            base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
        )
        active = resolve_active_trend_engine_id()
        eng = registry.get(active)
        return {
            "env_version": resolve_bundle_version(),
            "active_engine_id": active,
            "engine_loaded": eng is not None,
            "engine_version": eng.version() if eng else None,
        }

    v40_probe = _with_env("v40", _probe)
    v41_probe = _with_env("v41", _probe)

    v40_checksum = validate_trend_checksum(base_dir=base_dir, version="v40")
    v41_checksum = validate_trend_checksum(base_dir=base_dir, version="v41")

    passed = (
        v40_probe["active_engine_id"] == TREND_ENGINE_ID
        and v41_probe["active_engine_id"] == TREND_ENGINE_V41_ID
        and v40_probe["engine_loaded"]
        and v41_probe["engine_loaded"]
        and v40_checksum.get("valid")
        and v41_checksum.get("valid")
    )

    return {
        "phase": "17D",
        "passed": passed,
        "instructions": rollback_instructions(),
        "v40_switch": v40_probe,
        "v41_switch": v41_probe,
        "v40_checksum_unchanged": v40_checksum,
        "v41_checksum": v41_checksum,
        "instant_rollback": True,
        "no_code_change_required": True,
    }
