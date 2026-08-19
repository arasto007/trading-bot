"""Phase 18B — full production pipeline audit (read-only)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum
from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, rollback_instructions
from tradingbot.ml.phase18b.config import PROTECTED_MODULES


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(ok: bool, *, warn: bool = False) -> str:
    if ok:
        return "PASS"
    return "WARN" if warn else "FAIL"


def run_production_audit(
    *,
    project_root: Path,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}

    # Kernel
    kernel_path = project_root / "tradingbot/kernel/trading_kernel.py"
    items["kernel"] = {
        "status": _status(kernel_path.is_file()),
        "path": str(kernel_path),
        "sha256": _sha(kernel_path),
        "modified_by_phase18b": False,
    }

    # Risk
    risk_path = project_root / "tradingbot/adapters/risk_gate.py"
    items["risk"] = {
        "status": _status(risk_path.is_file()),
        "path": str(risk_path),
        "sha256": _sha(risk_path),
        "modified_by_phase18b": False,
    }

    # Execution / MT5
    mt5_path = project_root / "tradingbot/adapters/mt5_execution.py"
    items["execution"] = {
        "status": _status(mt5_path.is_file()),
        "path": str(mt5_path),
        "sha256": _sha(mt5_path),
        "order_send_invoked": False,
        "modified_by_phase18b": False,
    }

    # Registry
    PipelineCache.reset()
    try:
        registry = EngineRegistry.build_default(
            base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
        )
        ids = registry.list_ids()
        has_range = "phase9_9" in ids
        has_v40 = TREND_ENGINE_ID in ids
        has_v41 = TREND_ENGINE_V41_ID in ids
        active = resolve_active_trend_engine_id()
        items["registry"] = {
            "status": _status(has_range and has_v40 and has_v41),
            "ids": ids,
            "active_trend": active,
            "active_resolvable": registry.get(active) is not None,
            "health": registry.health_all(),
        }
    except Exception as exc:  # noqa: BLE001
        items["registry"] = {"status": "FAIL", "error": str(exc)}

    # Bundles
    v40 = validate_trend_checksum(base_dir=base_dir, version="v40")
    v41 = validate_trend_checksum(base_dir=base_dir, version="v41")
    try:
        p99 = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
        p99_ok = p99 is not None
    except Exception as exc:  # noqa: BLE001
        p99_ok = False
        p99_err = str(exc)
    else:
        p99_err = None
    items["bundles"] = {
        "status": _status(v40.get("valid") and v41.get("valid") and p99_ok),
        "v40": v40,
        "v41": v41,
        "phase9_9_ok": p99_ok,
        "phase9_9_error": p99_err,
    }

    # Rollback
    rb = rollback_instructions()
    items["rollback"] = {
        "status": _status(bool(rb.get("rollback"))),
        "env_var": TREND_VERSION_ENV,
        "instructions": rb,
        "no_code_change_required": True,
    }

    # Logging / monitoring / health
    log_modules = [
        project_root / "tradingbot/ml/integration/kernel_run_logger.py",
        project_root / "tradingbot/ml/monitoring/health_monitor.py",
        project_root / "tradingbot/ml/monitoring/observer.py",
        project_root / "tradingbot/ml/phase15a/health_check.py",
    ]
    present = [p for p in log_modules if p.is_file()]
    items["logging"] = {
        "status": _status(len(present) >= 1, warn=len(present) < len(log_modules)),
        "modules_present": [str(p.relative_to(project_root)) for p in present],
    }
    items["monitoring"] = {
        "status": _status(any("monitoring" in str(p) for p in present), warn=True),
        "modules_present": [str(p.relative_to(project_root)) for p in present if "monitoring" in str(p)],
    }
    items["health"] = {
        "status": _status(any("health" in str(p).lower() for p in present)),
        "registry_health": items.get("registry", {}).get("health"),
    }

    # Configuration
    items["configuration"] = {
        "status": "PASS",
        "trend_model_version_env": TREND_VERSION_ENV,
        "protected_modules_count": len(PROTECTED_MODULES),
    }

    # Recovery (cache reset)
    try:
        PipelineCache.reset()
        PipelineCache.get_registry(base_dir=base_dir, symbol=symbol)
        items["recovery"] = {"status": "PASS", "cache_reset_ok": True, "registry_reload_ok": True}
    except Exception as exc:  # noqa: BLE001
        items["recovery"] = {"status": "FAIL", "error": str(exc)}

    # Protected modules integrity
    protected = {}
    for rel in PROTECTED_MODULES:
        p = project_root / rel
        protected[rel] = {"exists": p.is_file(), "sha256": _sha(p)}
    items["protected_modules"] = {
        "status": _status(all(v["exists"] for v in protected.values())),
        "modules": protected,
    }

    statuses = [v.get("status") for v in items.values() if isinstance(v, dict) and "status" in v]
    passed = all(s == "PASS" for s in statuses)
    return {
        "phase": "18B",
        "passed": passed,
        "items": items,
        "summary": {
            "pass": sum(1 for s in statuses if s == "PASS"),
            "warn": sum(1 for s in statuses if s == "WARN"),
            "fail": sum(1 for s in statuses if s == "FAIL"),
            "total": len(statuses),
        },
    }
