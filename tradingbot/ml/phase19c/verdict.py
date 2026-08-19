"""Phase 19C — improvement acceptance verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19c.config import TARGET_EXPECTANCY, TARGET_MAX_DD, TARGET_PF, VERDICTS


def _trades_per_year(trades: int, days: int) -> float:
    if days <= 0:
        return 0.0
    return round(trades * (365.0 / days), 1)


def build_comparison(
    *,
    phase19a_perf: dict[str, Any],
    phase19c_perf: dict[str, Any],
    days: int,
    rollback: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase19a": {
            "profit_factor": phase19a_perf.get("profit_factor"),
            "expectancy_r": phase19a_perf.get("expectancy_r"),
            "maximum_drawdown_r": phase19a_perf.get("maximum_drawdown_r"),
            "win_rate": phase19a_perf.get("win_rate"),
            "trades_per_year": _trades_per_year(int(phase19a_perf.get("trades", 0)), days),
            "net_profit_r": phase19a_perf.get("net_profit_r"),
        },
        "phase19c": {
            "profit_factor": phase19c_perf.get("profit_factor"),
            "expectancy_r": phase19c_perf.get("expectancy_r"),
            "maximum_drawdown_r": phase19c_perf.get("maximum_drawdown_r"),
            "win_rate": phase19c_perf.get("win_rate"),
            "trades_per_year": _trades_per_year(int(phase19c_perf.get("trades", 0)), days),
            "net_profit_r": phase19c_perf.get("net_profit_r"),
        },
        "delta": {
            "profit_factor": round(
                float(phase19c_perf.get("profit_factor", 0)) - float(phase19a_perf.get("profit_factor", 0)),
                4,
            ),
            "expectancy_r": round(
                float(phase19c_perf.get("expectancy_r", 0)) - float(phase19a_perf.get("expectancy_r", 0)),
                4,
            ),
            "maximum_drawdown_r": round(
                float(phase19c_perf.get("maximum_drawdown_r", 0)) - float(phase19a_perf.get("maximum_drawdown_r", 0)),
                4,
            ),
            "win_rate": round(
                float(phase19c_perf.get("win_rate", 0)) - float(phase19a_perf.get("win_rate", 0)),
                4,
            ),
            "net_profit_r": round(
                float(phase19c_perf.get("net_profit_r", 0)) - float(phase19a_perf.get("net_profit_r", 0)),
                4,
            ),
        },
        "rollback_equivalence": rollback.get("equivalence"),
        "rollback_passed": bool(rollback.get("passed")),
    }


def determine_verdict(
    *,
    comparison_3y: dict[str, Any],
    rollback: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
) -> str:
    perf = comparison_3y.get("phase19c", {})
    pf = float(perf.get("profit_factor", 0))
    exp = float(perf.get("expectancy_r", 0))
    dd = abs(float(perf.get("maximum_drawdown_r", 0)))

    targets_met = pf >= TARGET_PF and exp >= TARGET_EXPECTANCY and dd <= TARGET_MAX_DD
    rollback_ok = bool(rollback.get("passed"))
    wf_ok = bool(walkforward.get("stable"))
    mc_ok = bool(montecarlo.get("passed"))

    improved_vs_19a = (
        float(comparison_3y.get("delta", {}).get("profit_factor", 0)) > 0
        and float(comparison_3y.get("delta", {}).get("expectancy_r", 0)) >= 0
    )

    if rollback_ok and wf_ok and mc_ok and targets_met and improved_vs_19a:
        return "IMPROVEMENT_ACCEPTED"
    return "ROLLBACK_REQUIRED"


def build_final_report(
    *,
    verdict: str,
    filter_settings: dict[str, Any],
    comparison: dict[str, Any],
    windows: dict[str, Any],
    rollback: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "19C",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "filters_implemented": ["rsi_mid", "adx_15_50"],
        "filter_settings": filter_settings,
        "targets": {
            "profit_factor": TARGET_PF,
            "expectancy_r": TARGET_EXPECTANCY,
            "max_drawdown_r": TARGET_MAX_DD,
        },
        "comparison_vs_phase19a": comparison,
        "windows": windows,
        "rollback_validation": {
            "passed": rollback.get("passed"),
            "equivalence": rollback.get("equivalence"),
        },
        "walkforward": {
            "stable": walkforward.get("stable"),
            "stable_folds": walkforward.get("stable_folds"),
            "n_folds": walkforward.get("n_folds"),
        },
        "montecarlo": {
            "passed": montecarlo.get("passed"),
            "failure_rate": montecarlo.get("failure_rate"),
            "mean_pf_stress": montecarlo.get("mean_pf_stress"),
        },
        "recommendation": (
            "RSI + ADX filters validated — keep enabled in production."
            if verdict == "IMPROVEMENT_ACCEPTED"
            else "Disable filters (ENABLE_RSI_FILTER=false, ENABLE_ADX_FILTER=false) to restore Phase 19A behavior."
        ),
    }
