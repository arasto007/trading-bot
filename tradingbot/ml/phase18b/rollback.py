"""Phase 18B — repeated v40↔v41 rollback validation."""

from __future__ import annotations

import os
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id


def _probe(base_dir: str | None, symbol: str) -> dict[str, Any]:
    PipelineCache.reset()
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    active = resolve_active_trend_engine_id()
    eng = registry.get(active)
    return {
        "active": active,
        "loaded": eng is not None,
        "ids": registry.list_ids(),
        "checksum": eng.checksum() if eng else None,
    }


def run_rollback_cycles(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    sequence: tuple[str, ...] = ("v40", "v41", "v40", "v41"),
) -> dict[str, Any]:
    prev = os.environ.get(TREND_VERSION_ENV)
    probes: list[dict[str, Any]] = []
    expected = {
        "v40": TREND_ENGINE_ID,
        "v41": TREND_ENGINE_V41_ID,
    }
    try:
        for ver in sequence:
            os.environ[TREND_VERSION_ENV] = ver
            probe = _probe(base_dir, symbol)
            probe["requested"] = ver
            probe["expected_engine"] = expected[ver]
            probe["match"] = probe["active"] == expected[ver] and probe["loaded"]
            probes.append(probe)
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev

    # Identical recovery: both v40 probes match each other; both v41 probes match
    v40_probes = [p for p in probes if p["requested"] == "v40"]
    v41_probes = [p for p in probes if p["requested"] == "v41"]
    identical_v40 = len({(p["active"], p["checksum"]) for p in v40_probes}) == 1
    identical_v41 = len({(p["active"], p["checksum"]) for p in v41_probes}) == 1

    v40_chk = validate_trend_checksum(base_dir=base_dir, version="v40")
    v41_chk = validate_trend_checksum(base_dir=base_dir, version="v41")

    passed = (
        all(p["match"] for p in probes)
        and identical_v40
        and identical_v41
        and v40_chk.get("valid")
        and v41_chk.get("valid")
    )
    return {
        "phase": "18B",
        "passed": passed,
        "sequence": list(sequence),
        "probes": probes,
        "identical_recovery_v40": identical_v40,
        "identical_recovery_v41": identical_v41,
        "no_cache_corruption": identical_v40 and identical_v41,
        "v40_checksum_valid": v40_chk.get("valid"),
        "v41_checksum_valid": v41_chk.get("valid"),
    }
