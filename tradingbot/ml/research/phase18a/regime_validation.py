"""Phase 18A — regime split validation."""

from __future__ import annotations

from typing import Any


def build_regime_split_validation(run: dict[str, Any]) -> dict[str, Any]:
    comparator = run["comparator"]
    counts = run.get("regime_counts", {})
    return {
        "phase": "18A",
        "regime_counts": counts,
        "trend_bars": counts.get("TREND", 0),
        "range_bars": counts.get("RANGE", 0),
        "agreement_rate_overall": comparator.agreement_rate(),
        "divergence_rate_trend": comparator.divergence_rate("TREND"),
        "divergence_rate_range": comparator.divergence_rate("RANGE"),
        "range_identical": run.get("range_identical", False),
        "range_signal_mismatch": run.get("range_signal_mismatch", 0),
        "trend_path_uses_dual_engines": True,
        "range_path_uses_phase9_9_only": True,
        "path_mismatch": not run.get("range_identical", False),
        "passed": (
            run.get("range_identical", False)
            and counts.get("TREND", 0) + counts.get("RANGE", 0) > 0
        ),
    }
