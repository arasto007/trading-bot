"""Phase 19D — live safety certification (read-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingbot.ml.phase18b.health import run_health_report
from tradingbot.ml.phase18b.live_safety import run_live_safety
from tradingbot.ml.phase18b.operational import run_operational_readiness
from tradingbot.ml.phase18b.rollback import run_rollback_cycles
from tradingbot.ml.phase18c.shutdown import validate_shutdown
from tradingbot.ml.phase18c.startup import validate_startup
from tradingbot.ml.phase19c.rollback import validate_rollback as validate_filter_rollback


def run_live_safety_certification(
    *,
    candles,
    dataset,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Read-only operational safety checks — no production modifications."""
    root = project_root or Path(__file__).resolve().parents[3]

    rollback_v40 = run_rollback_cycles(base_dir=base_dir, symbol=symbol)
    filter_rollback = validate_filter_rollback(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
    )
    health = run_health_report(base_dir=base_dir, symbol=symbol)
    live_safety = run_live_safety(project_root=root, base_dir=base_dir, symbol=symbol)
    operational = run_operational_readiness(project_root=root, base_dir=base_dir, symbol=symbol)
    startup = validate_startup(project_root=root, base_dir=base_dir, symbol=symbol)
    shutdown = validate_shutdown(base_dir=base_dir, symbol=symbol)

    checks = {
        "rollback_v40_v41": bool(rollback_v40.get("passed")),
        "filter_rollback": bool(filter_rollback.get("passed")),
        "health": bool(health.get("passed")),
        "live_safety": bool(live_safety.get("passed")),
        "logging": bool(operational.get("passed")),
        "monitoring": bool(operational.get("passed")),
        "recovery": bool(operational.get("passed")),
        "startup": bool(startup.get("passed")),
        "shutdown": bool(shutdown.get("passed")),
    }
    passed = all(checks.values())

    return {
        "phase": "19D",
        "read_only": True,
        "passed": passed,
        "checks": checks,
        "rollback_v40_v41": {
            "passed": rollback_v40.get("passed"),
            "cycles": len(rollback_v40.get("sequence", [])),
        },
        "filter_rollback": {
            "passed": filter_rollback.get("passed"),
            "equivalence": filter_rollback.get("equivalence"),
        },
        "health_summary": {
            "passed": health.get("passed", health.get("healthy")),
            "engines": health.get("engines"),
        },
        "live_safety_summary": {
            "passed": live_safety.get("passed"),
            "order_send_calls": live_safety.get("order_send_calls", 0),
        },
        "operational_summary": {
            "passed": operational.get("passed"),
        },
        "startup_passed": startup.get("passed"),
        "shutdown_passed": shutdown.get("passed"),
    }
