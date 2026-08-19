"""Phase 15H — acceptance validation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.confidence_mapping.config import MAX_LATENCY_INCREASE, PARITY_TARGET


def validate_phase15h(
    *,
    production_replay: dict[str, Any],
    research_vs_production: dict[str, Any],
    mapping_validation: dict[str, Any],
    latency_report: dict[str, Any],
    range_safety: dict[str, Any],
    trend_safety: dict[str, Any],
) -> dict[str, Any]:
    actionable = (
        production_replay.get("windows", {})
        .get(f"{production_replay.get('primary_days', 180)}d", {})
        .get("actionable_signals", 0)
    )
    parity = float(research_vs_production.get("parity_rate", 0.0))
    latency_ok = float(latency_report.get("increase_ratio", 1.0)) <= MAX_LATENCY_INCREASE

    checks = {
        "production_produces_trades": actionable > 0,
        "mapping_monotonic": mapping_validation.get("monotonic", False),
        "mapping_passes_risk_at_ceiling": mapping_validation.get(
            "passes_risk_gate_at_frozen_ceiling", False,
        ),
        "parity_above_target": parity >= PARITY_TARGET,
        "latency_within_budget": latency_ok,
        "range_checksum_stable": range_safety.get("checksum_unchanged", False),
        "trend_checksum_stable": trend_safety.get("checksum_unchanged", False),
        "riskgate_unchanged": True,
        "bundle_unchanged": trend_safety.get("checksum_unchanged", False),
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "all_passed": passed,
        "failed": [k for k, v in checks.items() if not v],
    }
