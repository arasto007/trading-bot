"""Phase 19A — profitability verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.config import VERDICTS


def determine_verdict(
    *,
    performance_summary: dict[str, Any],
    robustness: dict[str, Any],
    capital: dict[str, Any],
    final_score: dict[str, Any],
) -> str:
    """
    Decision based ONLY on measured profitability and robustness.
    """
    perf_1y = performance_summary.get("windows", {}).get("365d", {}).get("performance", {})
    perf_3y = performance_summary.get("windows", {}).get("1095d", {}).get("performance", {})

    pf_1y = float(perf_1y.get("profit_factor", 0))
    pf_3y = float(perf_3y.get("profit_factor", 0))
    exp_3y = float(perf_3y.get("expectancy_r", 0))
    dd_3y = abs(float(perf_3y.get("maximum_drawdown_r", 0)))
    trades_3y = int(perf_3y.get("trades", 0))

    cap_1000 = capital.get("levels", {}).get("1000", {})
    ruin = bool(cap_1000.get("risk_of_ruin", True))
    robust_pass = bool(robustness.get("passed", False))
    max_fail = float(robustness.get("max_failure_rate", 1.0))
    overall = float(final_score.get("overall_score", 0))

    full_criteria = (
        pf_3y >= 1.25
        and pf_1y >= 1.1
        and exp_3y > 0
        and trades_3y >= 30
        and dd_3y <= 25
        and robust_pass
        and max_fail < 0.25
        and not ruin
        and overall >= 65
    )
    if full_criteria:
        return "READY_FOR_FULL_PRODUCTION"

    small_criteria = (
        pf_1y >= 1.05
        and exp_3y >= 0
        and trades_3y >= 15
        and max_fail < 0.40
        and overall >= 50
    )
    if small_criteria:
        return "READY_FOR_SMALL_CAPITAL"

    return "NOT_READY_FOR_REAL_CAPITAL"


def build_final_report(
    *,
    verdict: str,
    performance_summary: dict[str, Any],
    regime: dict[str, Any],
    trade_quality: dict[str, Any],
    capital: dict[str, Any],
    robustness: dict[str, Any],
    final_score: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "19A",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "read_only": True,
        "production_modified": False,
        "system_under_test": {
            "trend": "trend_rf_v41",
            "range": "phase9_9",
            "execution": "simulation_only",
        },
        "final_score": final_score,
        "performance_highlights": {
            "1y": performance_summary.get("windows", {}).get("365d", {}).get("performance"),
            "3y": performance_summary.get("windows", {}).get("1095d", {}).get("performance"),
        },
        "regime_summary": {
            k: {
                "trades": v.get("trades"),
                "pf": v.get("profit_factor"),
                "net_profit_r": v.get("net_profit_r"),
            }
            for k, v in regime.get("regimes", {}).items()
        },
        "robustness_passed": robustness.get("passed"),
        "capital_1000": capital.get("levels", {}).get("1000"),
        "recommendation": {
            "READY_FOR_FULL_PRODUCTION": "Measured profitability and robustness support full production capital.",
            "READY_FOR_SMALL_CAPITAL": "Positive edge with caveats — limit capital and monitor drawdown.",
            "NOT_READY_FOR_REAL_CAPITAL": "Profitability or robustness below threshold — do not deploy real capital.",
        }.get(verdict, ""),
    }
