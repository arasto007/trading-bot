"""Phase 19D — final audit aggregation."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.regime_analysis import analyze_regimes


def run_final_audit(
    *,
    certification: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stress: dict[str, Any],
    capital: dict[str, Any],
    live_safety: dict[str, Any],
    final_score: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    regime = analyze_regimes(trades)
    perf_3y = certification.get("windows", {}).get("1095d", {}).get("performance", {})

    dimensions = {
        "architecture": {
            "passed": live_safety.get("passed", False),
            "score": final_score.get("dimensions", {}).get("architecture"),
            "note": "Production stack + filters + safety validated read-only",
        },
        "profitability": {
            "passed": certification.get("passed", False),
            "score": final_score.get("dimensions", {}).get("profitability"),
            "profit_factor_3y": perf_3y.get("profit_factor"),
            "expectancy_3y": perf_3y.get("expectancy_r"),
        },
        "robustness": {
            "passed": montecarlo.get("passed", False),
            "score": final_score.get("dimensions", {}).get("robustness"),
            "max_failure_rate": montecarlo.get("max_failure_rate"),
        },
        "consistency": {
            "passed": walkforward.get("passed", False),
            "score": final_score.get("dimensions", {}).get("consistency"),
            "stable_folds": walkforward.get("stable_folds"),
        },
        "risk": {
            "passed": abs(float(perf_3y.get("maximum_drawdown_r", 0))) <= 20.0,
            "score": final_score.get("dimensions", {}).get("risk"),
            "max_drawdown_3y_r": perf_3y.get("maximum_drawdown_r"),
            "capital_no_ruin_1000": not capital.get("levels", {}).get("1000", {}).get("risk_of_ruin", True),
        },
        "deployment": {
            "passed": live_safety.get("passed", False) and montecarlo.get("passed", False),
            "score": final_score.get("dimensions", {}).get("deployment"),
        },
    }

    passed = all(d["passed"] for d in dimensions.values()) and stress.get("passed", False)

    return {
        "phase": "19D",
        "read_only": True,
        "passed": passed,
        "overall_score": final_score.get("overall_score"),
        "dimensions": dimensions,
        "regime_summary": {
            k: {"trades": v.get("trades"), "pf": v.get("profit_factor")}
            for k, v in regime.get("regimes", {}).items()
        },
        "production_modified": False,
    }
