"""Phase 15I — acceptance validation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase15i.config import (
    MIN_RANGE_CONTRIBUTION,
    REGIME_PARITY_TARGET,
    TREND_STABILITY_TOLERANCE,
)


def validate_phase15i(
    *,
    range_pipeline: dict[str, Any],
    router_balance: dict[str, Any],
    regime_distribution: dict[str, Any],
    recovery_replay: dict[str, Any],
    baseline_replay: dict[str, Any],
    range_safety: dict[str, Any],
    trend_safety: dict[str, Any],
    recovery_justified: bool,
) -> dict[str, Any]:
    primary = recovery_replay.get("primary_days", 180)
    win = recovery_replay.get("windows", {}).get(f"{primary}d", {})
    base_win = baseline_replay.get("windows", {}).get(f"{primary}d", {})

    range_trades = int(win.get("range_trades", 0))
    trend_trades = int(win.get("trend_trades", 0))
    base_range = int(base_win.get("range_trades", 0))
    base_trend = int(base_win.get("trend_trades", 0))
    if base_trend == 0 and trend_trades == 0:
        trend_delta = 0.0
    else:
        trend_delta = abs(trend_trades - base_trend) / max(base_trend, trend_trades, 1)
    total = max(range_trades + trend_trades, 1)
    range_pct = range_trades / total

    checks = {
        "root_cause_identified": bool(range_pipeline.get("diagnosis")),
        "recovery_mathematically_justified": recovery_justified,
        "range_contributes_trades": range_trades > 0,
        "range_measurable_contribution": range_trades >= max(1, int(base_range * 0.95)) and (
            range_trades / max(range_trades + trend_trades, 1) >= MIN_RANGE_CONTRIBUTION
            or range_trades > base_range
        ),
        "trend_performance_stable": trend_delta <= TREND_STABILITY_TOLERANCE,
        "router_balanced": router_balance.get("router_calls_phase9_9_correctly", False),
        "regime_distribution_within_1pct": regime_distribution.get("within_1pct", False),
        "range_checksum_stable": range_safety.get("checksum_unchanged", False),
        "trend_checksum_stable": trend_safety.get("checksum_unchanged", False),
        "no_bundle_modification": range_safety.get("bundle_touched", True) is False,
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "all_passed": passed,
        "failed": [k for k, v in checks.items() if not v],
        "range_trades": range_trades,
        "trend_trades": trend_trades,
        "range_contribution_pct": round(range_pct, 4),
        "trend_stability_delta": round(trend_delta, 4),
    }
