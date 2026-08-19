"""Phase 18C — engine / registry validation."""

from __future__ import annotations

import os
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, rollback_instructions


def validate_engines(*, base_dir: str | None = None, symbol: str = "XAUUSD") -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}

    PipelineCache.reset()
    try:
        registry = EngineRegistry.build_default(
            base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
        )
        ids = registry.list_ids()
        items["engine_registry"] = {
            "status": "PASS" if all(x in ids for x in ("phase9_9", TREND_ENGINE_ID, TREND_ENGINE_V41_ID)) else "FAIL",
            "ids": ids,
            "health": registry.health_all(),
        }
    except Exception as exc:  # noqa: BLE001
        items["engine_registry"] = {"status": "FAIL", "error": str(exc)}
        registry = None

    # Kernel adapter (construct only — no trading)
    try:
        from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
        PipelineCache.reset()
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
        items["kernel_adapter"] = {
            "status": "PASS" if adapter is not None else "FAIL",
            "has_deps": hasattr(adapter, "_deps"),
        }
    except Exception as exc:  # noqa: BLE001
        items["kernel_adapter"] = {"status": "FAIL", "error": str(exc)}

    # Pipeline cache
    try:
        PipelineCache.reset()
        r1 = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        r2 = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        items["pipeline_cache"] = {
            "status": "PASS" if r1 is not None and r2 is not None else "FAIL",
            "ids": r1.list_ids() if r1 else [],
        }
    except Exception as exc:  # noqa: BLE001
        items["pipeline_cache"] = {"status": "FAIL", "error": str(exc)}

    # Trend / range engines
    if registry is not None:
        v40 = registry.get(TREND_ENGINE_ID)
        v41 = registry.get(TREND_ENGINE_V41_ID)
        rng = registry.get("phase9_9")
        items["recovered_trend_engine"] = {
            "status": "PASS" if v40 is not None and getattr(v40, "inner", None) is not None else "FAIL",
            "engine_id": TREND_ENGINE_ID,
        }
        items["trend_v41_engine"] = {
            "status": "PASS" if v41 is not None and getattr(v41, "inner", None) is not None else "FAIL",
            "engine_id": TREND_ENGINE_V41_ID,
        }
        items["range_engine"] = {
            "status": "PASS" if rng is not None and getattr(rng, "inner", None) is not None else "FAIL",
            "engine_id": "phase9_9",
        }
    else:
        items["recovered_trend_engine"] = {"status": "FAIL"}
        items["trend_v41_engine"] = {"status": "FAIL"}
        items["range_engine"] = {"status": "FAIL"}

    # Confidence mapping / feature alignment presence
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    conf_path = root / "tradingbot/ml/confidence_mapping/production_adapter.py"
    align_path = root / "tradingbot/ml/feature_alignment/factory.py"
    items["confidence_mapping"] = {"status": "PASS" if conf_path.is_file() else "FAIL", "path": str(conf_path)}
    items["feature_alignment"] = {"status": "PASS" if align_path.is_file() else "FAIL", "path": str(align_path)}

    # Rollback switch
    prev = os.environ.get(TREND_VERSION_ENV)
    try:
        os.environ[TREND_VERSION_ENV] = "v40"
        PipelineCache.reset()
        a40 = resolve_active_trend_engine_id()
        os.environ[TREND_VERSION_ENV] = "v41"
        PipelineCache.reset()
        a41 = resolve_active_trend_engine_id()
        items["rollback_switch"] = {
            "status": "PASS" if a40 == TREND_ENGINE_ID and a41 == TREND_ENGINE_V41_ID else "FAIL",
            "v40_active": a40,
            "v41_active": a41,
            "instructions": rollback_instructions(),
        }
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev

    statuses = [v["status"] for v in items.values()]
    return {
        "phase": "18C",
        "passed": all(s == "PASS" for s in statuses),
        "items": items,
        "summary": {
            "pass": sum(1 for s in statuses if s == "PASS"),
            "fail": sum(1 for s in statuses if s == "FAIL"),
        },
    }
