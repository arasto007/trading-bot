"""Phase 13.7 — initial audit of Phase 13.6 findings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase13_7.config import phase13_6_reports_dir


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def build_initial_audit(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = phase13_6_reports_dir(base_dir)
    final = _load(root / "final_phase13_6_report.json")
    comparison = _load(root / "model_comparison.json")
    wf = _load(root / "walk_forward_results.json")
    failure = _load(root / "failure_analysis.json")

    phase136 = final.get("PHASE_13_6_FINAL_REPORT", {})
    best_cfg = phase136.get("3_best_configuration", {})
    opt_metrics = final.get("optimized_metrics", {})
    robustness = final.get("robustness", {})

    low_trade_winners = [
        r
        for r in comparison.get("comparison_table", [])
        if int(r.get("trades", 0)) < 100 and float(r.get("profit_factor", 0)) > 1.0
    ]

    return {
        "phase": "13.7",
        "source": "phase13_6_reports",
        "selected_configurations": {
            "phase13_6_best": best_cfg,
            "policy": best_cfg.get("policy", "A"),
            "min_confidence": best_cfg.get("min_confidence"),
            "regime_params": best_cfg.get("regime_params"),
        },
        "overfit_cases": {
            "overfit_detected": final.get("overfit_analysis", {}).get("overfit_detected", False),
            "overfit_risk": final.get("overfit_analysis", {}).get("overfit_risk"),
            "robustness_score": robustness.get("robustness_score"),
            "stable": robustness.get("stable", False),
        },
        "low_trade_count_winners": low_trade_winners,
        "phase13_6_optimized_trades": opt_metrics.get("trades", 0),
        "phase13_6_optimized_pf": opt_metrics.get("profit_factor", 0.0),
        "regime_failures": {
            "top_failure_driver": failure.get("top_driver"),
            "category_counts": failure.get("category_counts", {}),
        },
        "trend_engine_issue": {
            "trend_only_trades": next(
                (
                    r.get("trades", 0)
                    for r in comparison.get("comparison_table", [])
                    if r.get("model") == "Trend Engine only"
                ),
                0,
            ),
            "note": "Trend engine produced zero trades in Phase 13.6 router comparison",
        },
        "walk_forward_summary": {
            "mean_pf": wf.get("mean_profit_factor"),
            "robustness_score": wf.get("robustness", {}).get("robustness_score"),
            "positive_pf_windows": wf.get("robustness", {}).get("positive_pf_windows"),
        },
        "why_overfit_happened": [
            "Phase 13.6 composite score ranked PF without minimum trade floor",
            "min_confidence=0.35 collapsed sample to 2 trades",
            "Aggressive regime thresholds (adx 20/15) reduced routing opportunities",
            "Walk-forward mean PF inflated by single-trade windows",
        ],
        "fixes_planned": [
            "Minimum 100 trade hard reject, 300 strong reject",
            "Robust composite score with trade consistency weight",
            "Router variant comparison with stability validation",
            "Trend routing funnel debug",
            "Monte Carlo perturbation testing",
        ],
    }
