"""Phase 19D — deployment readiness assessment."""

from __future__ import annotations

from typing import Any


def build_deployment_readiness(
    *,
    certification: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stress: dict[str, Any],
    capital: dict[str, Any],
    live_safety: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    gates = {
        "backtest_certification": certification.get("passed", False),
        "walkforward_stable": walkforward.get("passed", False),
        "montecarlo_passed": montecarlo.get("passed", False),
        "stress_test_passed": stress.get("passed", False),
        "capital_simulation_passed": capital.get("passed", False),
        "live_safety_passed": live_safety.get("passed", False),
        "final_audit_passed": audit.get("passed", False),
    }
    all_pass = all(gates.values())
    return {
        "phase": "19D",
        "read_only": True,
        "gates": gates,
        "all_gates_pass": all_pass,
        "system": {
            "trend": "trend_rf_v41",
            "range": "phase9_9",
            "filters": ["rsi_mid", "adx_15_50"],
        },
        "rollback_instructions": [
            "TREND_MODEL_VERSION=v40 for model rollback",
            "ENABLE_RSI_FILTER=false ENABLE_ADX_FILTER=false for filter rollback",
        ],
        "ready_for_deployment": all_pass,
    }
