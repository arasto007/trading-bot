"""Phase 17C — Phase9.9 RANGE regression (100% parity required)."""

from __future__ import annotations

from typing import Any


def evaluate_range_regression(shadow_comparison: dict[str, Any]) -> dict[str, Any]:
    """Verify RANGE kernel contribution is identical across all horizons."""
    windows = shadow_comparison.get("windows", {})
    per_horizon: list[dict[str, Any]] = []
    all_identical = True

    for key, win in windows.items():
        frozen_range = int(win.get("frozen", {}).get("kernel", {}).get("range_contribution", -1))
        research_range = int(win.get("research", {}).get("kernel", {}).get("range_contribution", -2))
        frozen_engine = int(win.get("frozen", {}).get("engine", {}).get("range_actionable", -1))
        research_engine = int(win.get("research", {}).get("engine", {}).get("range_actionable", -2))
        identical = (
            frozen_range == research_range
            and frozen_engine == research_engine
            and win.get("comparison", {}).get("range_identical", False)
        )
        if not identical:
            all_identical = False
        per_horizon.append({
            "horizon": key,
            "frozen_kernel_range": frozen_range,
            "research_kernel_range": research_range,
            "frozen_engine_range": frozen_engine,
            "research_engine_range": research_engine,
            "identical": identical,
            "delta": abs(frozen_range - research_range),
        })

    return {
        "phase": "17C",
        "requirement": "100% RANGE parity",
        "passed": all_identical and len(per_horizon) > 0,
        "parity_pct": 100.0 if all_identical and per_horizon else 0.0,
        "horizons": per_horizon,
        "failure_reason": None if all_identical else "RANGE output diverged between frozen and research paths",
    }
