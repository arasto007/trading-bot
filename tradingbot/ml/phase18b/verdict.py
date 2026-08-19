"""Phase 18B — final GO/NO-GO verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase18b.config import VERDICTS


def build_go_live_checks(
    *,
    audit: dict[str, Any],
    failure: dict[str, Any],
    stability: dict[str, Any],
    rollback: dict[str, Any],
    live_safety: dict[str, Any],
    operational: dict[str, Any],
    checklist: dict[str, Any],
) -> dict[str, bool]:
    return {
        "all_safety_checks_pass": checklist.get("no_fail", False) and audit.get("passed", False),
        "rollback_pass": rollback.get("passed", False),
        "failure_injection_pass": failure.get("passed", False),
        "long_run_stability_pass": stability.get("passed", False),
        "no_execution_bugs": live_safety.get("passed", False),
        "no_cache_bugs": (
            live_safety.get("no_stale_cache", False)
            and rollback.get("no_cache_corruption", False)
            and stability.get("cache_behavior_ok", False)
        ),
        "no_production_regressions": (
            audit.get("passed", False)
            and failure.get("production_intact_after", False)
        ),
        "operational_ready": operational.get("passed", False),
        "checklist_no_fail": checklist.get("no_fail", False),
        "checklist_all_pass": checklist.get("all_pass", False),
    }


def determine_verdict(checks: dict[str, bool]) -> str:
    full_required = (
        "all_safety_checks_pass",
        "rollback_pass",
        "failure_injection_pass",
        "long_run_stability_pass",
        "no_execution_bugs",
        "no_cache_bugs",
        "no_production_regressions",
    )
    if all(checks.get(k, False) for k in full_required) and checks.get("checklist_all_pass", False):
        return "READY_FOR_FULL_LIVE"

    limited_required = (
        "rollback_pass",
        "failure_injection_pass",
        "long_run_stability_pass",
        "no_execution_bugs",
        "no_cache_bugs",
        "no_production_regressions",
        "checklist_no_fail",
    )
    if all(checks.get(k, False) for k in limited_required):
        return "READY_FOR_LIMITED_LIVE"

    return "NOT_READY_FOR_LIVE"


def build_go_live_recommendation(
    *,
    verdict: str,
    checks: dict[str, bool],
    checklist: dict[str, Any],
) -> dict[str, Any]:
    recs = {
        "READY_FOR_FULL_LIVE": [
            "All gates passed — controlled full live is permitted.",
            "Keep TREND_MODEL_VERSION=v41 with instant rollback to v40.",
            "Monitor latency, agreement, and RANGE parity in first live session.",
        ],
        "READY_FOR_LIMITED_LIVE": [
            "Critical safety gates passed with non-blocking warnings.",
            "Start limited live (reduced size / hours) with active monitoring.",
            "Resolve WARN checklist items before full live.",
        ],
        "NOT_READY_FOR_LIVE": [
            "One or more critical gates failed.",
            "Do not enable live trading.",
            "Review FAIL items in final_checklist.json.",
        ],
    }
    return {
        "phase": "18B",
        "verdict": verdict,
        "checks": checks,
        "checklist_summary": checklist.get("summary"),
        "recommendations": recs.get(verdict, []),
        "rollback_env": "TREND_MODEL_VERSION=v40",
        "active_candidate": "trend_rf_v41",
    }


def build_final_report(
    *,
    verdict: str,
    checks: dict[str, bool],
    checklist: dict[str, Any],
    recommendation: dict[str, Any],
    audit: dict[str, Any],
    failure: dict[str, Any],
    stability: dict[str, Any],
    rollback: dict[str, Any],
    live_safety: dict[str, Any],
    operational: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "18B",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "mode": "PRODUCTION_READINESS_VALIDATION",
        "production_modified": False,
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "checklist_summary": checklist.get("summary"),
        "recommendation": recommendation,
        "summaries": {
            "audit": audit.get("summary"),
            "failure_injection": {
                "passed": failure.get("passed"),
                "cases_passed": failure.get("cases_passed"),
                "cases_total": failure.get("cases_total"),
            },
            "stability": {
                "passed": stability.get("passed"),
                "prediction_stability": stability.get("prediction_stability"),
                "memory_peak_delta_mb": stability.get("memory", {}).get("peak_delta_mb"),
            },
            "rollback": {
                "passed": rollback.get("passed"),
                "sequence": rollback.get("sequence"),
            },
            "live_safety": {"passed": live_safety.get("passed")},
            "operational": operational.get("summary"),
        },
    }
