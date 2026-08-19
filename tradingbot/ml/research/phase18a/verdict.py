"""Phase 18A — shadow validation verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase18a.config import (
    MAX_LATENCY_OVERHEAD,
    MAX_RANDOM_DIVERGENCE,
    MIN_AGREEMENT_RATE,
    VERDICTS,
)


def build_checks(
    *,
    stats: dict[str, Any],
    safety: dict[str, Any],
    regime: dict[str, Any],
    reports_present: bool,
) -> dict[str, bool]:
    clusters = stats.get("clusters", {})
    divergence = float(stats.get("divergence_rate", 1.0))
    random_spike = bool(clusters.get("random_spike", False))
    unexplained_spike = random_spike and divergence > MAX_RANDOM_DIVERGENCE

    return {
        "full_replay_completed": int(stats.get("bars_evaluated", 0)) > 0,
        "no_runtime_crashes": int(stats.get("runtime_crashes", 0)) == 0,
        "range_not_degraded": bool(stats.get("range_not_degraded", False)),
        "latency_overhead_ok": bool(stats.get("latency_ok", False)),
        "agreement_or_explainable": bool(stats.get("agreement_ok", False)),
        "no_order_send": int(stats.get("order_send_calls", 0)) == 0 and safety.get("passed", False),
        "reports_present": reports_present,
        "no_path_mismatch": not bool(regime.get("path_mismatch", True)),
        "no_unexplained_divergence_spike": not unexplained_spike,
        "bundles_intact": safety.get("passed", False),
    }


def determine_verdict(checks: dict[str, bool]) -> str:
    hard_fail = (
        not checks.get("no_order_send", False)
        or not checks.get("reports_present", False)
        or not checks.get("no_path_mismatch", False)
        or not checks.get("no_unexplained_divergence_spike", False)
        or not checks.get("no_runtime_crashes", False)
        or not checks.get("full_replay_completed", False)
    )
    if hard_fail:
        return "SHADOW_FAILED"

    soft = (
        checks.get("range_not_degraded", False)
        and checks.get("latency_overhead_ok", False)
        and checks.get("agreement_or_explainable", False)
        and checks.get("bundles_intact", False)
    )
    if soft:
        return "READY_FOR_CONTROLLED_LIVE"
    return "SHADOW_NEEDS_REVIEW"


def build_final_report(
    *,
    verdict: str,
    checks: dict[str, bool],
    stats: dict[str, Any],
    safety: dict[str, Any],
    regime: dict[str, Any],
    latency: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "18A",
        "verdict": verdict,
        "mode": "READ_ONLY_SHADOW",
        "production_impact": False,
        "live_orders": False,
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v),
        "checks_total": len(checks),
        "verdicts_allowed": list(VERDICTS),
        "metrics": {
            "agreement_rate": stats.get("agreement_rate"),
            "divergence_rate": stats.get("divergence_rate"),
            "divergence_rate_trend": stats.get("divergence_rate_trend"),
            "divergence_rate_range": stats.get("divergence_rate_range"),
            "latency_overhead_pct": latency.get("overhead_pct"),
            "equity_divergence": stats.get("equity_divergence"),
            "bars_evaluated": stats.get("bars_evaluated"),
        },
        "thresholds": {
            "min_agreement_rate": MIN_AGREEMENT_RATE,
            "max_latency_overhead": MAX_LATENCY_OVERHEAD,
            "max_random_divergence": MAX_RANDOM_DIVERGENCE,
        },
        "safety": safety,
        "regime_split": {
            "range_identical": regime.get("range_identical"),
            "path_mismatch": regime.get("path_mismatch"),
        },
        "stability": stats.get("stability"),
        "recommendation": (
            "v41 behaviorally safe for controlled live shadow monitoring"
            if verdict == "READY_FOR_CONTROLLED_LIVE"
            else "Review divergence / latency before live exposure"
        ),
    }
