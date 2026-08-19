"""Phase 9.8 — robustness and overfitting analysis."""

from __future__ import annotations

from typing import Any


def compute_robustness_score(
    windows: list[dict[str, Any]],
    aggregate: dict[str, Any],
) -> float:
    """Score 0–100 from consistency, profitability, and train/validation gap."""
    if not windows:
        return 0.0

    pf_vals = [float(w.get("profit_factor", 0.0) or 0.0) for w in windows]
    exp_vals = [float(w.get("expectancy", 0.0) or 0.0) for w in windows]
    pf_pass = sum(1 for v in pf_vals if v >= 1.0) / len(windows)
    exp_pass = sum(1 for v in exp_vals if v > 0.0) / len(windows)
    consistency = float(aggregate.get("stability_score", {}).get("consistency_score", 0.0))

    gaps = [abs(float(w.get("train_val_auc_gap", 0.0) or 0.0)) for w in windows]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    gap_penalty = min(1.0, mean_gap * 4.0)

    raw = 100.0 * (0.30 * pf_pass + 0.30 * exp_pass + 0.25 * consistency + 0.15 * (1.0 - gap_penalty))
    return round(max(0.0, min(100.0, raw)), 2)


def assess_overfitting_risk(windows: list[dict[str, Any]], robustness_score: float) -> str:
    gaps = [abs(float(w.get("train_val_auc_gap", 0.0) or 0.0)) for w in windows]
    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    degradations = [
        float(w.get("performance_degradation", 0.0) or 0.0)
        for w in windows
        if w.get("performance_degradation") is not None
    ]
    mean_degradation = sum(degradations) / len(degradations) if degradations else 0.0

    if mean_gap > 0.12 or robustness_score < 45 or mean_degradation > 0.25:
        return "HIGH"
    if mean_gap > 0.06 or robustness_score < 70 or mean_degradation > 0.12:
        return "MEDIUM"
    return "LOW"


def analyze_robustness(
    windows: list[dict[str, Any]],
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    """Full robustness analysis payload."""
    robustness_score = compute_robustness_score(windows, aggregate)
    overfitting_risk = assess_overfitting_risk(windows, robustness_score)

    mean_metrics = aggregate.get("mean_metrics", {})
    mean_pf = float(mean_metrics.get("profit_factor", 0.0))
    mean_exp = float(mean_metrics.get("expectancy", 0.0))
    mean_wr = float(mean_metrics.get("win_rate", 0.0))

    if mean_pf >= 1.2 and mean_exp > 0 and robustness_score >= 70:
        final_decision = "READY FOR PAPER TRADING"
    else:
        final_decision = "NEEDS MORE RESEARCH"

    gaps = [float(w.get("train_val_auc_gap", 0.0) or 0.0) for w in windows]
    regime_dependency = {
        "regime": "RANGE",
        "note": "All windows evaluated on Phase 9.7 RANGE regime filter",
    }

    return {
        "robustness_score": robustness_score,
        "overfitting_risk": overfitting_risk,
        "final_decision": final_decision,
        "mean_profit_factor": mean_pf,
        "mean_expectancy": mean_exp,
        "mean_win_rate": mean_wr,
        "worst_window": aggregate.get("worst_window"),
        "best_window": aggregate.get("best_window"),
        "performance_stability": aggregate.get("stability_score", {}),
        "train_test_gap": {
            "mean_auc_gap": round(sum(abs(g) for g in gaps) / len(gaps), 4) if gaps else 0.0,
            "max_auc_gap": round(max((abs(g) for g in gaps), default=0.0), 4),
        },
        "market_regime_dependency": regime_dependency,
        "overfitting_indicators": {
            "high_auc_gap_windows": sum(1 for g in gaps if abs(g) > 0.1),
            "negative_expectancy_windows": sum(
                1 for w in windows if float(w.get("expectancy", 0.0) or 0.0) <= 0.0
            ),
        },
    }
