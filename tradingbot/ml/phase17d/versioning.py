"""Phase 17D — trend bundle version resolution and rollback."""

from __future__ import annotations

from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase17d.config import DEFAULT_ACTIVE_VERSION, ROLLBACK_VERSION, read_trend_model_version


def resolve_bundle_version() -> str:
    """Resolve bundle version token (v40 | v41) from TREND_MODEL_VERSION env."""
    return read_trend_model_version()


def resolve_active_trend_engine_id() -> str:
    """Map active bundle version to registry engine id."""
    version = resolve_bundle_version()
    if version == ROLLBACK_VERSION:
        return TREND_ENGINE_ID
    return TREND_ENGINE_V41_ID


def version_to_engine_id(version: str) -> str:
    if version == ROLLBACK_VERSION:
        return TREND_ENGINE_ID
    return TREND_ENGINE_V41_ID


def engine_id_to_version(engine_id: str) -> str:
    if engine_id == TREND_ENGINE_ID:
        return ROLLBACK_VERSION
    return DEFAULT_ACTIVE_VERSION


def rollback_instructions() -> dict[str, str]:
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV

    return {
        "active_default": DEFAULT_ACTIVE_VERSION,
        "rollback": f"set {TREND_VERSION_ENV}={ROLLBACK_VERSION}",
        "promote": f"set {TREND_VERSION_ENV}={DEFAULT_ACTIVE_VERSION}",
        "no_code_change_required": "true",
    }
