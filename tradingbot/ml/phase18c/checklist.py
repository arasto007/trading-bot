"""Phase 18C — go-live checklist (PASS / WARN / FAIL)."""

from __future__ import annotations

from typing import Any


def _item(name: str, status: str, detail: str = "") -> dict[str, str]:
    return {"item": name, "status": status, "detail": detail}


def _block_status(block: dict[str, Any]) -> str:
    if block.get("passed"):
        # surface WARNs from summary if present
        summary = block.get("summary") or {}
        if summary.get("fail", 0) > 0:
            return "FAIL"
        if summary.get("warn", 0) > 0:
            return "WARN"
        return "PASS"
    return "FAIL"


def build_go_live_checklist(
    *,
    environment: dict[str, Any],
    mt5: dict[str, Any],
    bundles: dict[str, Any],
    engines: dict[str, Any],
    configuration: dict[str, Any],
    startup: dict[str, Any],
    shutdown: dict[str, Any],
) -> dict[str, Any]:
    items = [
        _item("environment", _block_status(environment)),
        _item("models", _block_status(bundles)),
        _item("registry", "PASS" if engines.get("items", {}).get("engine_registry", {}).get("status") == "PASS" else "FAIL"),
        _item("bundles", _block_status(bundles)),
        _item("rollback", "PASS" if engines.get("items", {}).get("rollback_switch", {}).get("status") == "PASS" else "FAIL"),
        _item("monitoring", "PASS" if configuration.get("items", {}).get("monitoring", {}).get("status") in ("PASS", "WARN") else "FAIL",
              configuration.get("items", {}).get("monitoring", {}).get("status", "")),
        _item("logging", "PASS" if configuration.get("items", {}).get("logging", {}).get("status") == "PASS" else "FAIL"),
        _item("mt5", _block_status(mt5)),
        _item("health", "PASS" if startup.get("passed") else "FAIL"),
        _item("configuration", _block_status(configuration)),
        _item("startup", "PASS" if startup.get("passed") and startup.get("no_exceptions") else "FAIL"),
        _item("shutdown", _block_status(shutdown)),
        _item("no_exceptions", "PASS" if startup.get("no_exceptions") else "FAIL"),
        _item("rollback_available", "PASS" if engines.get("items", {}).get("rollback_switch", {}).get("status") == "PASS" else "FAIL"),
    ]

    # Expand WARN items from environment/mt5
    for name, block in (environment.get("items") or {}).items():
        if block.get("status") == "WARN":
            items.append(_item(f"environment_{name}", "WARN"))
    for name, block in (mt5.get("items") or {}).items():
        if block.get("status") == "WARN":
            items.append(_item(f"mt5_{name}", "WARN"))

    summary = {
        "pass": sum(1 for i in items if i["status"] == "PASS"),
        "warn": sum(1 for i in items if i["status"] == "WARN"),
        "fail": sum(1 for i in items if i["status"] == "FAIL"),
        "total": len(items),
    }
    return {
        "phase": "18C",
        "items": items,
        "summary": summary,
        "no_fail": summary["fail"] == 0,
    }
