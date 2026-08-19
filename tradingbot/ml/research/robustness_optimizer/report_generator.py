"""Phase 9.9 — robustness optimization report generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_9_feature_selection_path,
    phase9_9_model_comparison_path,
    phase9_9_robustness_report_path,
)


def _risk_improved(baseline: str, current: str) -> bool:
    """Legacy ordinal overfitting comparison (superseded by numeric mean_auc_gap check)."""
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    return order.get(current, 2) < order.get(baseline, 2)


def _optional_float(value: Any) -> float | None:
    """Parse a metric without treating missing values as zero."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean_auc_gap_improved(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """Numeric overfitting control: fail closed when either gap is missing."""
    candidate_gap = _optional_float(candidate.get("mean_auc_gap"))
    baseline_gap = _optional_float(baseline.get("mean_auc_gap"))
    if candidate_gap is None or baseline_gap is None:
        return False
    return candidate_gap < baseline_gap


def evaluate_acceptance(
    best: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """Check Phase 9.9 acceptance vs Phase 9.8 baseline."""
    base_score = float(baseline.get("robustness_score", 0.0) or 0.0)
    best_score = float(best.get("robustness_score", 0.0) or 0.0)
    base_risk = str(baseline.get("overfitting_risk", "HIGH"))
    best_risk = str(best.get("overfitting_risk", "HIGH"))
    mean_exp = float(best.get("mean_expectancy", 0.0) or 0.0)
    profitable = int(best.get("profitable_windows", 0) or 0)
    window_count = int(best.get("window_count", 0) or 0)
    baseline_mean_auc_gap = _optional_float(baseline.get("mean_auc_gap"))
    best_mean_auc_gap = _optional_float(best.get("mean_auc_gap"))

    checks = {
        "robustness_improved": best_score > base_score,
        "overfitting_risk_decreased": _mean_auc_gap_improved(best, baseline),
        "mean_expectancy_positive": mean_exp > 0,
        "profitable_windows_ge_4": profitable >= 4 and window_count >= 4,
        "probability_quality_passed": bool(best.get("probability_gate_passed", False)),
    }
    passed = all(checks.values())
    return {
        "checks": checks,
        "final_verdict": "PASS" if passed else "FAIL",
        "baseline_robustness_score": base_score,
        "best_robustness_score": best_score,
        "robustness_delta": round(best_score - base_score, 2),
        "baseline_overfitting_risk": base_risk,
        "best_overfitting_risk": best_risk,
        "baseline_mean_auc_gap": baseline_mean_auc_gap,
        "best_mean_auc_gap": best_mean_auc_gap,
        "overfitting_check_mode": "numeric_mean_auc_gap",
        "probability_gate": {
            "passed": bool(best.get("probability_gate_passed", False)),
            "acceptance_reason": best.get("acceptance_reason"),
            "rejection_reason": best.get("rejection_reason"),
            "buy_coverage_pct": best.get("buy_coverage_pct"),
            "sell_coverage_pct": best.get("sell_coverage_pct"),
            "probability_std": best.get("probability_std"),
        },
    }


def save_reports(
    *,
    symbol: str,
    timeframe: str,
    seed: int,
    feature_research: dict[str, Any],
    regime_analysis: dict[str, Any],
    ranked: list[dict[str, Any]],
    best: dict[str, Any] | None,
    acceptance: dict[str, Any],
    baseline: dict[str, Any],
    integrity: dict[str, Any],
    experiments: list[dict[str, Any]],
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    reports_root = phase9_9_robustness_report_path(base_dir).parent
    reports_root.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()

    feature_path = phase9_9_feature_selection_path(base_dir)
    feature_payload = {**feature_research, "generated_at_utc": generated}
    feature_path.write_text(json.dumps(feature_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    comparison_path = phase9_9_model_comparison_path(base_dir)
    comparison_payload = {
        "phase": "9.9",
        "generated_at_utc": generated,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "seed": seed,
        "candidate_count": len(ranked),
        "ranked_candidates": ranked,
        "rank_one_candidate": ranked[0] if ranked else None,
        "baseline_phase9_8": baseline,
        "best_candidate": best,
        "production_winner_rule": "ACCEPTANCE_PASS_HIGHEST_COMPOSITE",
    }
    comparison_path.write_text(json.dumps(comparison_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    main_path = phase9_9_robustness_report_path(base_dir)
    main_payload = {
        "phase": "9.9",
        "generated_at_utc": generated,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "seed": seed,
        "integrity": integrity,
        "baseline_phase9_8": baseline,
        "best_candidate": best,
        "acceptance": acceptance,
        "regime_analysis": regime_analysis,
        "mean_metrics_best": {
            "profit_factor": best.get("mean_profit_factor") if best else None,
            "expectancy": best.get("mean_expectancy") if best else None,
            "robustness_score": best.get("robustness_score") if best else None,
            "overfitting_risk": best.get("overfitting_risk") if best else None,
            "buy_coverage_pct": best.get("buy_coverage_pct") if best else None,
            "sell_coverage_pct": best.get("sell_coverage_pct") if best else None,
            "probability_std": best.get("probability_std") if best else None,
        },
        "experiment_count": len(experiments),
        "final_verdict": acceptance.get("final_verdict", "FAIL"),
        "shuffle": False,
    }
    main_path.write_text(json.dumps(main_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "robustness_report": main_path,
        "model_comparison": comparison_path,
        "feature_selection": feature_path,
    }
