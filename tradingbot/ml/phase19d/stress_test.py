"""Phase 19D — market condition stress tests."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.metrics import compute_performance


def _segment_perf(trades: list[dict[str, Any]], name: str) -> dict[str, Any]:
    perf = compute_performance(trades)
    passed = perf["trades"] >= 5 and perf["profit_factor"] >= 1.0 and perf["expectancy_r"] >= 0
    return {
        "segment": name,
        "trades": perf["trades"],
        "profit_factor": perf["profit_factor"],
        "expectancy_r": perf["expectancy_r"],
        "maximum_drawdown_r": perf["maximum_drawdown_r"],
        "win_rate": perf["win_rate"],
        "passed": passed,
    }


def run_stress_test(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    if not accepted:
        return {"phase": "19D", "passed": False, "note": "no_trades", "segments": []}

    adx_vals = [float(t.get("adx", 0)) for t in accepted]
    adx_med = float(np.median(adx_vals)) if adx_vals else 25.0

    segments = [
        _segment_perf(
            [t for t in accepted if float(t.get("adx", 0)) >= adx_med],
            "high_volatility",
        ),
        _segment_perf(
            [t for t in accepted if float(t.get("adx", 0)) < adx_med],
            "low_volatility",
        ),
        _segment_perf([t for t in accepted if t.get("regime") == "TREND"], "trend_regime"),
        _segment_perf([t for t in accepted if t.get("regime") == "RANGE"], "range_regime"),
        _segment_perf(accepted, "mixed_market"),
    ]

    # Segments with too few trades are WARN not FAIL
    scored = [s for s in segments if s["trades"] >= 5]
    passed_count = sum(1 for s in scored if s["passed"])
    passed = passed_count >= max(1, len(scored) * 2 // 3)

    return {
        "phase": "19D",
        "adx_median_split": adx_med,
        "segments": segments,
        "passed": passed,
        "segments_passed": passed_count,
        "segments_evaluated": len(scored),
    }
