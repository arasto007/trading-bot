"""Phase 18C — pre-live verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase18c.config import VERDICTS


def build_checks(
    *,
    environment: dict[str, Any],
    mt5: dict[str, Any],
    bundles: dict[str, Any],
    engines: dict[str, Any],
    configuration: dict[str, Any],
    startup: dict[str, Any],
    shutdown: dict[str, Any],
    checklist: dict[str, Any],
) -> dict[str, bool]:
    registry_ok = engines.get("items", {}).get("engine_registry", {}).get("status") == "PASS"
    rollback_ok = engines.get("items", {}).get("rollback_switch", {}).get("status") == "PASS"
    return {
        "environment_pass": environment.get("passed", False),
        "mt5_pass": mt5.get("passed", False),
        "bundles_pass": bundles.get("passed", False),
        "registry_pass": registry_ok,
        "startup_pass": startup.get("passed", False),
        "shutdown_pass": shutdown.get("passed", False),
        "no_exceptions": startup.get("no_exceptions", False),
        "no_missing_configuration": configuration.get("passed", False),
        "rollback_available": rollback_ok,
        "checklist_no_fail": checklist.get("no_fail", False),
        "engines_pass": engines.get("passed", False),
        "no_orders": mt5.get("order_send_calls", 0) == 0,
    }


def determine_verdict(checks: dict[str, bool]) -> str:
    required = (
        "environment_pass",
        "mt5_pass",
        "bundles_pass",
        "registry_pass",
        "startup_pass",
        "shutdown_pass",
        "no_exceptions",
        "no_missing_configuration",
        "rollback_available",
    )
    if all(checks.get(k, False) for k in required):
        return "READY_FOR_MARKET_OPEN"
    return "NOT_READY_FOR_MARKET_OPEN"


def build_final_report(
    *,
    verdict: str,
    checks: dict[str, bool],
    checklist: dict[str, Any],
    environment: dict[str, Any],
    mt5: dict[str, Any],
    bundles: dict[str, Any],
    engines: dict[str, Any],
    configuration: dict[str, Any],
    startup: dict[str, Any],
    shutdown: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "18C",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "mode": "PRE_LIVE_READINESS",
        "market_closed": True,
        "trading_attempted": False,
        "orders_sent": False,
        "production_modified": False,
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "checklist_summary": checklist.get("summary"),
        "summaries": {
            "environment": environment.get("summary"),
            "mt5": mt5.get("summary"),
            "bundles": bundles.get("summary"),
            "engines": engines.get("summary"),
            "configuration": configuration.get("summary"),
            "startup": {"passed": startup.get("passed"), "exceptions": startup.get("exceptions")},
            "shutdown": shutdown.get("summary"),
        },
        "recommendation": (
            "System is ready — start bot when market opens. No additional setup required."
            if verdict == "READY_FOR_MARKET_OPEN"
            else "Resolve FAIL items in go_live_checklist.json before market open."
        ),
    }
