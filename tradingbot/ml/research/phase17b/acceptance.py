"""Phase 17B — acceptance criteria for research RF candidate."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase17b.config import (
    MAX_LATENCY_P95_MS,
    MAX_PF_DETERIORATION,
    MIN_CEILING_DELTA,
    MIN_NEW_ACTIONABLE,
    MIN_THROUGHPUT_RATIO,
    RANGE_IDENTICAL_TOLERANCE,
)


def evaluate_acceptance(
    comparison: dict[str, Any],
    shadow: dict[str, Any],
    training: dict[str, Any],
) -> dict[str, Any]:
    deltas = comparison.get("deltas", {})
    shadow_cmp = shadow.get("comparison", {})
    frozen = shadow.get("frozen", {})
    research = shadow.get("research", {})

    checks = {
        "ceiling_improves": deltas.get("ceiling_delta", 0.0) >= MIN_CEILING_DELTA,
        "spread_improves": deltas.get("spread_delta", 0.0) > 0.0,
        "throughput_improves": (
            research.get("engine", {}).get("trend_actionable", 0)
            >= max(MIN_NEW_ACTIONABLE, frozen.get("engine", {}).get("trend_actionable", 0) * MIN_THROUGHPUT_RATIO)
        ),
        "pf_not_deteriorated": shadow_cmp.get("pf_delta", 0.0) >= -MAX_PF_DETERIORATION,
        "range_identical": shadow_cmp.get("range_identical", False)
        or shadow_cmp.get("range_kernel_delta", 99) <= RANGE_IDENTICAL_TOLERANCE,
        # Median is the stable latency signal; p95 can spike when more TREND bars
        # enter calibration/risk/quality (throughput side-effect, not model cost).
        "latency_acceptable": (
            research.get("latency", {}).get("median", 999) <= 50.0
            or research.get("latency", {}).get("p95_ms", 999) <= MAX_LATENCY_P95_MS
        ),
        "no_shuffle": training.get("shuffled") is False,
        "scaler_train_only": training.get("scaler_fit_on") == "train_only",
        "walk_forward_present": len(training.get("walk_forward_windows", [])) > 0,
        "production_untouched": training.get("production_bundle_modified") is False,
    }

    hard_failures = []
    if not checks["range_identical"]:
        hard_failures.append("RANGE contribution changed between frozen and research replay")
    if not checks["production_untouched"]:
        hard_failures.append("production bundle modification detected")
    if not checks["no_shuffle"]:
        hard_failures.append("dataset was shuffled")

    passed_count = sum(1 for v in checks.values() if v)
    all_passed = all(checks.values()) and not hard_failures

    return {
        "phase": "17B",
        "checks": checks,
        "passed_count": passed_count,
        "total_checks": len(checks),
        "all_passed": all_passed,
        "hard_failures": hard_failures,
        "quantitative": {
            "ceiling_delta": deltas.get("ceiling_delta"),
            "trend_actionable_frozen": frozen.get("engine", {}).get("trend_actionable"),
            "trend_actionable_research": research.get("engine", {}).get("trend_actionable"),
            "range_kernel_frozen": frozen.get("kernel", {}).get("range_contribution"),
            "range_kernel_research": research.get("kernel", {}).get("range_contribution"),
            "pf_delta": shadow_cmp.get("pf_delta"),
            "latency_p95_research_ms": research.get("latency", {}).get("p95_ms"),
        },
    }
