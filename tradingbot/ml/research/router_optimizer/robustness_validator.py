"""Phase 13.6 — robustness and overfit validation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.router_optimizer.router_optimizer import composite_score


def robustness_score(window_metrics: list[dict[str, Any]]) -> float:
    if not window_metrics:
        return 0.0
    pfs = [float(w.get("profit_factor", 0.0)) for w in window_metrics]
    exps = [float(w.get("expectancy", w.get("expectancy_r", 0.0))) for w in window_metrics]
    pf_std = float(np.std(pfs)) if len(pfs) > 1 else 0.0
    exp_std = float(np.std(exps)) if len(exps) > 1 else 0.0
    return round(max(0.0, 1.0 - pf_std) * 0.55 + max(0.0, 1.0 - exp_std) * 0.45, 4)


def overfit_analysis(train_metrics: dict[str, Any], test_metrics: dict[str, Any]) -> dict[str, Any]:
    train_pf = float(train_metrics.get("profit_factor", 0.0))
    test_pf = float(test_metrics.get("profit_factor", 0.0))
    train_exp = float(train_metrics.get("expectancy", train_metrics.get("expectancy_r", 0.0)))
    test_exp = float(test_metrics.get("expectancy", test_metrics.get("expectancy_r", 0.0)))
    pf_gap = round(train_pf - test_pf, 4)
    exp_gap = round(train_exp - test_exp, 4)
    risk = "low"
    if pf_gap > 0.5 or exp_gap > 0.4:
        risk = "moderate"
    if pf_gap > 1.0 or exp_gap > 0.8:
        risk = "high"
    return {
        "pf_gap": pf_gap,
        "expectancy_gap": exp_gap,
        "overfit_risk": risk,
        "overfit_detected": risk in ("moderate", "high"),
    }


def validate_robustness(walk_forward_windows: list[dict[str, Any]]) -> dict[str, Any]:
    active = [w for w in walk_forward_windows if not w.get("skipped")]
    score = robustness_score([w.get("metrics", {}) for w in active])
    pfs = [float(w.get("metrics", {}).get("profit_factor", 0.0)) for w in active]
    positive_years = sum(1 for pf in pfs if pf >= 1.0)
    return {
        "robustness_score": score,
        "windows_tested": len(active),
        "positive_pf_windows": positive_years,
        "stable": score >= 0.45 and positive_years >= max(1, len(active) // 2),
        "overfit_detected": False,
        "chronological": True,
        "shuffle": False,
    }
