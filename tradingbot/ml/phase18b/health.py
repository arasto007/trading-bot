"""Phase 18B — aggregated health report."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.health_check import run_health_checks
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum


def run_health_report(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    PipelineCache.reset()
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    try:
        phase15a = run_health_checks(base_dir=base_dir, registry=registry)
    except Exception as exc:  # noqa: BLE001
        phase15a = {"error": str(exc)}

    v40 = validate_trend_checksum(base_dir=base_dir, version="v40")
    v41 = validate_trend_checksum(base_dir=base_dir, version="v41")
    reg_health = registry.health_all()

    passed = (
        v40.get("valid", False)
        and v41.get("valid", False)
        and all(h.get("status") == "OK" for h in reg_health.values())
    )
    return {
        "phase": "18B",
        "passed": passed,
        "registry_health": reg_health,
        "v40_checksum": v40,
        "v41_checksum": v41,
        "phase15a_health": phase15a,
    }
