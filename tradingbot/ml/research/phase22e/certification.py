"""Phase 22E — live readiness and final certification verdict."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.research.phase22e.config import MAX_DRAWDOWN_PCT_LIMIT, PF_TARGET


def assess_live_readiness(
    profitability: dict[str, Any],
    portfolio: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stress: dict[str, Any],
    delta: dict[str, Any],
) -> dict[str, Any]:
    activity = profitability.get("activity") or {}
    cert = profitability.get("certification_summary") or {}

    checks = {
        "buy_and_sell_active": activity.get("buy_active") and activity.get("sell_active"),
        "m5_active": activity.get("m5_active"),
        "m15_active": activity.get("m15_active"),
        "h4_active": activity.get("h4_active"),
        "pf_target_met": cert.get("pf_target_met"),
        "positive_expectancy": cert.get("positive_expectancy"),
        "max_dd_within_limit": cert.get("max_dd_within_limit"),
        "portfolio_profitable": (portfolio.get("metrics") or {}).get("net_profit", 0) > 0,
        "no_regression_22d": delta.get("no_regression_vs_22d"),
        "walkforward_stable": walkforward.get("stable"),
        "montecarlo_passed": montecarlo.get("passed"),
        "stress_acceptable": stress.get("overall_passed", stress.get("passed")),
    }

    critical = [
        "m5_active",
        "m15_active",
        "h4_active",
        "no_regression_22d",
        "buy_and_sell_active",
    ]
    passed_critical = all(checks.get(k) for k in critical)
    passed_all = all(v for v in checks.values() if v is not None)

    if passed_all:
        verdict = "READY_FOR_DEMO_FORWARD_VALIDATION"
    elif passed_critical and cert.get("positive_expectancy"):
        verdict = "READY_FOR_DEMO_WITH_MONITORING"
    elif passed_critical:
        verdict = "ENGINE_VALIDATED_PROFITABILITY_PENDING"
    else:
        verdict = "NOT_READY_FOR_LIVE"

    return {
        "phase": "22E",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "checks": checks,
        "passed_critical": passed_critical,
        "passed_all_targets": passed_all,
        "pf_target": PF_TARGET,
        "max_dd_limit_pct": MAX_DRAWDOWN_PCT_LIMIT,
        "recommendation": _recommendation(verdict, checks),
    }


def build_final_report(
    *,
    profitability: dict[str, Any],
    portfolio: dict[str, Any],
    distribution: dict[str, Any],
    walkforward: dict[str, Any],
    montecarlo: dict[str, Any],
    stress: dict[str, Any],
    delta: dict[str, Any],
    live_readiness: dict[str, Any],
    backtests: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": "22E",
        "title": "Full Production Validation & Profitability Certification",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": "ClosedBar→TradingKernel→RegimeRouter→Trend_v41→phase9_9→Calibration→Confidence→Quality→Phase19C→Meta→RiskGate→SimExec",
        "fixes_under_test": "Phase22D (v41 Top5 full-series + TREND confidence recovery)",
        "optimization": False,
        "validation_only": True,
        "success_criteria": {
            "buy_sell_active": live_readiness["checks"].get("buy_and_sell_active"),
            "m5_m15_h4_active": all(
                live_readiness["checks"].get(k)
                for k in ("m5_active", "m15_active", "h4_active")
            ),
            "pf_gt_1_30": live_readiness["checks"].get("pf_target_met"),
            "positive_expectancy": live_readiness["checks"].get("positive_expectancy"),
            "max_dd_ok": live_readiness["checks"].get("max_dd_within_limit"),
            "portfolio_profitable": live_readiness["checks"].get("portfolio_profitable"),
            "no_22d_regression": live_readiness["checks"].get("no_regression_22d"),
        },
        "verdict": live_readiness["verdict"],
        "profitability_summary": profitability,
        "portfolio": portfolio,
        "distribution": distribution,
        "walkforward": walkforward,
        "montecarlo": montecarlo,
        "stress": stress,
        "delta_vs_prior_phases": delta,
        "live_readiness": live_readiness,
        "backtest_windows": list(backtests.keys()),
    }


def _recommendation(verdict: str, checks: dict) -> str:
    if verdict == "READY_FOR_DEMO_FORWARD_VALIDATION":
        return "Production path validated. Proceed to demo account forward validation with Phase 22D fixes."
    if verdict == "READY_FOR_DEMO_WITH_MONITORING":
        return "Engine and activity targets met; profitability certification incomplete — demo with strict monitoring."
    if verdict == "ENGINE_VALIDATED_PROFITABILITY_PENDING":
        return "22D engine fixes confirmed (BUY/SELL/M15/H4 active). Profitability targets not met on audit windows."
    missing = [k for k, v in checks.items() if not v]
    return f"Not ready for live. Failed checks: {', '.join(missing)}."
