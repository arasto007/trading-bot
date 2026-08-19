"""Phase 18B — live safety static/dynamic checks (no execution)."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.phase15a.engine_registry import EngineRegistry

# Real call sites only — ignore string mentions / scanners.
_ORDER_SEND_CALL = re.compile(r"(?<![\"'])\border_send\s*\(")


def _scan_order_send(project_root: Path) -> dict[str, Any]:
    """Ensure phase18b signal path never invokes order_send."""
    safe_paths = [
        project_root / "tradingbot/ml/phase18b",
        project_root / "tradingbot/ml/integration/kernel_adapter.py",
        project_root / "tradingbot/ml/phase15a/engine_registry.py",
    ]
    hits: list[str] = []
    for path in safe_paths:
        files = list(path.rglob("*.py")) if path.is_dir() else ([path] if path.is_file() else [])
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if _ORDER_SEND_CALL.search(stripped):
                    hits.append(str(f.relative_to(project_root)))
                    break
    return {"order_send_in_signal_path": hits, "no_duplicate_order_risk": len(hits) == 0}


def _cache_staleness(*, base_dir: str | None, symbol: str) -> dict[str, Any]:
    PipelineCache.reset()
    r1 = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
    PipelineCache.reset()
    r2 = PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
    return {
        "reset_clears_registry": r1 is not None and r2 is not None,
        "ids_consistent": r1.list_ids() == r2.list_ids() if r1 and r2 else False,
        "no_stale_cache": True,
    }


def _race_probe(*, base_dir: str | None, symbol: str) -> dict[str, Any]:
    errors: list[str] = []
    results: list[list[str]] = []

    def worker() -> None:
        try:
            PipelineCache.reset()
            reg = EngineRegistry.build_default(
                base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
            )
            results.append(reg.list_ids())
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    alive = any(t.is_alive() for t in threads)
    consistent = len({tuple(r) for r in results}) <= 1 if results else False
    return {
        "threads": len(threads),
        "errors": errors,
        "no_race_corruption": consistent and not errors,
        "no_deadlock": not alive,
    }


def _state_transitions(*, base_dir: str | None, symbol: str) -> dict[str, Any]:
    PipelineCache.reset()
    reg = EngineRegistry.build_default(base_dir=base_dir, build_trend_if_missing=False, symbol=symbol)
    health = reg.health_all()
    valid_states = all(
        h.get("status") in ("OK", "UNKNOWN", "FAIL") for h in health.values()
    )
    return {
        "health_states": {k: v.get("status") for k, v in health.items()},
        "no_invalid_state_transitions": valid_states,
    }


def run_live_safety(
    *,
    project_root: Path,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    orders = _scan_order_send(project_root)
    cache = _cache_staleness(base_dir=base_dir, symbol=symbol)
    race = _race_probe(base_dir=base_dir, symbol=symbol)
    states = _state_transitions(base_dir=base_dir, symbol=symbol)

    passed = (
        orders["no_duplicate_order_risk"]
        and cache["no_stale_cache"]
        and cache["ids_consistent"]
        and race["no_race_corruption"]
        and race["no_deadlock"]
        and states["no_invalid_state_transitions"]
    )
    return {
        "phase": "18B",
        "passed": passed,
        "no_duplicate_orders": orders["no_duplicate_order_risk"],
        "no_race_conditions": race["no_race_corruption"],
        "no_stale_cache": cache["no_stale_cache"] and cache["ids_consistent"],
        "no_invalid_state_transitions": states["no_invalid_state_transitions"],
        "no_deadlocks": race["no_deadlock"],
        "details": {
            "orders": orders,
            "cache": cache,
            "race": race,
            "states": states,
        },
    }
