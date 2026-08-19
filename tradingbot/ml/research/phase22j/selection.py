"""Phase 22J — engine candidate selection."""

from __future__ import annotations

from typing import Any


def compare_engine_candidates(results: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = next((r for r in results if r.get("candidate_id") == "22J-BASELINE"), {})
    ranked = sorted(
        [r for r in results if not r.get("error")],
        key=lambda r: (
            float(r.get("profit_factor") or 0),
            float(r.get("expectancy") or -999),
            int(r.get("trades") or 0),
        ),
        reverse=True,
    )
    rows = []
    b_pf = float(baseline.get("profit_factor") or 0)
    b_tr = baseline.get("trades") or 0
    for r in ranked:
        rows.append({
            **{k: r.get(k) for k in (
                "candidate_id", "title", "trades", "hold_pct", "profit_factor",
                "expectancy", "max_drawdown_pct", "win_rate_pct", "buy_emitted", "sell_emitted",
            )},
            "pf_delta": round(float(r.get("profit_factor") or 0) - b_pf, 4),
            "trades_delta": (r.get("trades") or 0) - b_tr,
        })
    return {
        "phase": "22J",
        "baseline": baseline,
        "ranked": rows,
        "best_by_pf": ranked[0].get("candidate_id") if ranked else None,
    }


def recommend_engine_fix(
    comparison: dict[str, Any],
    range_forensics: dict[str, Any],
    trend_forensics: dict[str, Any],
) -> dict[str, Any]:
    ranked = comparison.get("ranked") or []
    baseline = comparison.get("baseline") or {}
    candidates = [r for r in ranked if r.get("candidate_id") != "22J-BASELINE"]

    eligible = [
        c for c in candidates
        if float(c.get("profit_factor") or 0) >= float(baseline.get("profit_factor") or 0)
        and float(c.get("max_drawdown_pct") or 999) <= max(float(baseline.get("max_drawdown_pct") or 999) * 1.5, 15)
    ]
    pick = eligible[0] if eligible else (candidates[0] if candidates else baseline)

    range_root = (range_forensics.get("root_cause_hypothesis") or {}).get("primary", "unknown")
    trend_root = (trend_forensics.get("bottleneck") or {}).get("primary", "unknown")

    return {
        "phase": "22J",
        "selected_id": pick.get("candidate_id"),
        "title": pick.get("title"),
        "range_root_cause": range_root,
        "trend_root_cause": trend_root,
        "true_engine_bottleneck": "range_probability_dead_zone" if range_root == "probability_compression" else trend_root,
        "problem_category": _categorize(range_root, trend_root),
        "proposed_change": pick.get("title"),
        "predicted_impact": {
            "profit_factor_improvement": pick.get("pf_delta"),
            "trade_frequency_delta": pick.get("trades_delta"),
            "engineering_risk": "LOW" if pick.get("candidate_id", "").startswith("22J-00") else "MEDIUM",
        },
        "do_not_implement_yet": True,
    }


def _categorize(range_root: str, trend_root: str) -> str:
    if range_root in ("probability_compression", "feature_distribution_zeros", "symmetric_threshold_dead_zone"):
        return "features" if "feature" in range_root else "model_calibration"
    if trend_root == "rule_bottleneck":
        return "routing"
    if trend_root == "ml_threshold":
        return "model"
    return "feature_engineering"
