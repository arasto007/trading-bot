"""Phase 18B — final production checklist (PASS / WARN / FAIL)."""

from __future__ import annotations

from typing import Any


def _item(name: str, status: str, detail: str = "") -> dict[str, str]:
    return {"item": name, "status": status, "detail": detail}


def build_final_checklist(
    *,
    audit: dict[str, Any],
    failure: dict[str, Any],
    stability: dict[str, Any],
    rollback: dict[str, Any],
    live_safety: dict[str, Any],
    operational: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    items = [
        _item("production_audit", "PASS" if audit.get("passed") else "FAIL",
              f"fail={audit.get('summary', {}).get('fail', 0)}"),
        _item("failure_injection", "PASS" if failure.get("passed") else "FAIL",
              f"{failure.get('cases_passed')}/{failure.get('cases_total')}"),
        _item("long_run_stability", "PASS" if stability.get("passed") else "FAIL",
              f"mem_mb={stability.get('memory', {}).get('peak_delta_mb')}"),
        _item("prediction_stability", "PASS" if stability.get("prediction_stability") else "FAIL"),
        _item("cache_behavior", "PASS" if stability.get("cache_behavior_ok") else "FAIL"),
        _item("rollback_cycles", "PASS" if rollback.get("passed") else "FAIL",
              "→".join(rollback.get("sequence", []))),
        _item("identical_recovery", "PASS" if rollback.get("no_cache_corruption") else "FAIL"),
        _item("no_duplicate_orders", "PASS" if live_safety.get("no_duplicate_orders") else "FAIL"),
        _item("no_race_conditions", "PASS" if live_safety.get("no_race_conditions") else "FAIL"),
        _item("no_stale_cache", "PASS" if live_safety.get("no_stale_cache") else "FAIL"),
        _item("no_invalid_state_transitions", "PASS" if live_safety.get("no_invalid_state_transitions") else "FAIL"),
        _item("no_deadlocks", "PASS" if live_safety.get("no_deadlocks") else "FAIL"),
        _item("operational_readiness", "PASS" if operational.get("passed") else "FAIL"),
        _item("health_report", "PASS" if health.get("passed") else "WARN"),
        _item("bundles_intact", "PASS" if failure.get("production_intact_after") else "FAIL"),
        _item("no_execution_bugs", "PASS" if live_safety.get("passed") else "FAIL"),
        _item("no_cache_bugs", "PASS" if (
            live_safety.get("no_stale_cache") and rollback.get("no_cache_corruption")
        ) else "FAIL"),
        _item("no_production_regressions", "PASS" if (
            audit.get("passed") and failure.get("production_intact_after")
        ) else "FAIL"),
    ]

    # Operational WARNs
    for name, block in (operational.get("items") or {}).items():
        st = block.get("status", "PASS")
        if st == "WARN":
            items.append(_item(f"operational_{name}", "WARN", block.get("detail", "")))

    summary = {
        "pass": sum(1 for i in items if i["status"] == "PASS"),
        "warn": sum(1 for i in items if i["status"] == "WARN"),
        "fail": sum(1 for i in items if i["status"] == "FAIL"),
        "total": len(items),
    }
    return {
        "phase": "18B",
        "items": items,
        "summary": summary,
        "all_pass": summary["fail"] == 0 and summary["warn"] == 0,
        "no_fail": summary["fail"] == 0,
    }
