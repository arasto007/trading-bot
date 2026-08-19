"""Phase 22F — permanent development optimization workflow."""

from __future__ import annotations

from typing import Any


def build_development_workflow() -> dict[str, Any]:
    return {
        "phase": "22F",
        "name": "rapid_optimization_workflow",
        "mandate": "No long multi-month backtests until candidate passes fast validation",
        "stages": [
            {
                "stage": 1,
                "name": "fast_validation",
                "dataset": "A (7 trading days)",
                "timeframes": ["M5", "M15", "H4"],
                "target_runtime_min": "5-15",
                "command": "python -m tradingbot.ml.research.phase22f.run_rapid_validation --dataset A",
                "pass_criteria": {
                    "pf_improvement_vs_baseline": ">= 5% relative",
                    "expectancy_improved": True,
                    "no_dd_regression": True,
                    "buy_sell_balance_maintained": True,
                },
            },
            {
                "stage": 2,
                "name": "medium_validation",
                "dataset": "C (30 trading days)",
                "timeframes": ["M5", "M15", "H4"],
                "target_runtime_min": "30-45",
                "command": "python -m tradingbot.ml.research.phase22f.run_rapid_validation --dataset C",
                "pass_criteria": {
                    "pf_gte": 1.1,
                    "positive_expectancy": True,
                    "max_dd_pct_lte": 30,
                },
            },
            {
                "stage": 3,
                "name": "candidate_gate",
                "rule": "Only stage-2 passers proceed to production integration proposal",
                "requires": "Separate approved phase for any production change",
            },
            {
                "stage": 4,
                "name": "final_certification",
                "reference": "Phase 22E full chronological certification",
                "windows": ["1m", "3m", "6m", "1y", "3y"],
                "when": "After fast+medium pass AND explicit approval",
            },
        ],
        "forbidden": [
            "Threshold tuning without evidence",
            "Production changes during research",
            "Skipping stage 1 for multi-month backtests",
            "Optimization by guessing",
        ],
    }
