"""Phase 20B — live system stability verdict."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase20b.config import (
    GATE_MAX_DD_R,
    GATE_MAX_REJECTION_RATE,
    GATE_MIN_EXPECTANCY,
    GATE_MIN_HEALTH_SCORE,
    GATE_MIN_PF,
    MIN_LIVE_TRADES,
    VERDICTS,
)


def determine_verdict(
    *,
    observation: dict[str, Any],
    performance: dict[str, Any],
    drawdown: dict[str, Any],
    execution: dict[str, Any],
    health: dict[str, Any],
    capital: dict[str, Any],
) -> str:
    """Verdict based only on observed metrics."""
    overall = performance.get("overall") or {}
    trades = int(overall.get("trades", 0))
    pf = float(overall.get("profit_factor", 0))
    exp = float(overall.get("expectancy_r", 0))
    dd = abs(float(drawdown.get("maximum_drawdown_r", 0)))
    score = float(health.get("overall_score", 0))
    rej = float(execution.get("rejection_rate", 0))
    broker = int(execution.get("broker_samples", 0))

    gates = {
        "min_trades": trades >= MIN_LIVE_TRADES,
        "profit_factor": pf >= GATE_MIN_PF,
        "expectancy": exp >= GATE_MIN_EXPECTANCY,
        "drawdown": dd <= GATE_MAX_DD_R,
        "health_score": score >= GATE_MIN_HEALTH_SCORE,
        "capital_stable": bool(capital.get("passed")),
        "execution_ok": broker == 0 or rej <= GATE_MAX_REJECTION_RATE,
        "drawdown_passed": bool(drawdown.get("passed", False)),
        "path_observation": bool(observation.get("path_observation_available") or observation.get("trades")),
    }

    # Require core profitability/risk/health gates
    required = (
        "min_trades",
        "profit_factor",
        "expectancy",
        "drawdown",
        "health_score",
        "capital_stable",
        "execution_ok",
        "path_observation",
    )
    if all(gates.get(k) for k in required):
        return "LIVE_SYSTEM_STABLE"
    return "LIVE_SYSTEM_UNSTABLE"


def build_final_report(
    *,
    verdict: str,
    observation: dict[str, Any],
    performance: dict[str, Any],
    drawdown: dict[str, Any],
    execution: dict[str, Any],
    filters: dict[str, Any],
    capital: dict[str, Any],
    risk_stability: dict[str, Any],
    health: dict[str, Any],
    trade_quality: dict[str, Any],
) -> dict[str, Any]:
    overall = performance.get("overall") or {}
    return {
        "phase": "20B",
        "verdict": verdict,
        "verdicts_allowed": list(VERDICTS),
        "read_only": True,
        "production_modified": False,
        "data_source": observation.get("data_source"),
        "broker_live_samples": observation.get("broker_live_samples", 0),
        "system_under_observation": {
            "trend": "trend_rf_v41",
            "range": "phase9_9",
            "filters": ["rsi_mid", "adx_15_50"],
            "deployment": "phase20a",
        },
        "performance_highlights": {
            "trades": overall.get("trades"),
            "profit_factor": overall.get("profit_factor"),
            "expectancy_r": overall.get("expectancy_r"),
            "maximum_drawdown_r": overall.get("maximum_drawdown_r"),
            "win_rate": overall.get("win_rate"),
        },
        "health_score": health.get("overall_score"),
        "health_dimensions": health.get("dimensions"),
        "execution": {
            "passed": execution.get("passed"),
            "rejection_rate": execution.get("rejection_rate"),
            "latency_p95_ms": (execution.get("latency") or {}).get("p95_ms"),
        },
        "filters": filters.get("summary"),
        "capital": {
            "passed": capital.get("passed"),
            "recommended_risk_pct": capital.get("recommended_risk_pct"),
        },
        "trade_quality_mean": trade_quality.get("mean_overall_quality"),
        "risk_stability": risk_stability,
        "recommendation": {
            "LIVE_SYSTEM_STABLE": (
                "Live path metrics are stable — continue Phase 20A controlled capital with monitoring."
            ),
            "LIVE_SYSTEM_UNSTABLE": (
                "Live metrics do not meet stability gates — keep exposure minimal, "
                "review reports, and do not scale capital."
            ),
        }.get(verdict, ""),
    }
