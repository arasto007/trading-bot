"""Phase 22E — stress scenarios on production backtest path."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase22e.config import ValidationWindow
from tradingbot.ml.research.phase22e.metrics import compute_extended_metrics, trades_to_mc_records
from tradingbot.ml.research.phase22e.runner import run_production_backtest

STRESS_SCENARIOS = (
    {"name": "baseline", "spread_pips": None, "slippage_pips": None, "variable_spread": None},
    {"name": "high_spread", "spread_pips": 5.0, "slippage_pips": None, "variable_spread": True},
    {"name": "low_spread", "spread_pips": 1.0, "slippage_pips": None, "variable_spread": False},
    {"name": "high_slippage", "spread_pips": None, "slippage_pips": 2.5, "variable_spread": True},
    {"name": "missed_ticks", "spread_pips": 3.5, "slippage_pips": 1.5, "variable_spread": True},
    {"name": "delayed_execution", "spread_pips": 2.5, "slippage_pips": 1.2, "variable_spread": True},
)


async def run_stress_suite(
    timeframe: str,
    window: ValidationWindow,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for scenario in STRESS_SCENARIOS:
        name = scenario["name"]
        bt = await run_production_backtest(
            timeframe,
            window,
            spread_pips=scenario["spread_pips"],
            slippage_pips=scenario["slippage_pips"],
            variable_spread=scenario["variable_spread"],
            skip_hold_chain=True,
        )
        m = bt["metrics_window"]
        results[name] = {
            "trades": bt["window_trades_count"],
            "profit_factor": m.get("profit_factor"),
            "expectancy": m.get("expectancy"),
            "net_profit": m.get("net_profit"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "win_rate_pct": m.get("win_rate_pct"),
            "passed": _stress_pass(m, name),
        }

    volatility = _volatility_segments(results)
    return {
        "phase": "22E",
        "timeframe": timeframe,
        "window": window.to_dict(),
        "scenarios": results,
        "volatility_regimes": volatility,
        "overall_passed": all(v.get("passed", False) for v in results.values() if v.get("trades", 0) >= 3),
    }


def _stress_pass(metrics: dict, scenario: str) -> bool:
    trades = metrics.get("total_trades", 0)
    if trades < 3:
        return scenario in ("baseline", "low_spread")
    pf = metrics.get("profit_factor")
    pf_val = float(pf) if pf not in (None, "inf") else 999.0
    exp = float(metrics.get("expectancy", 0))
    dd = float(metrics.get("max_drawdown_pct", 100))
    if scenario == "baseline":
        return pf_val >= 1.0 and exp >= 0
    return dd <= 35.0 and exp > -5.0


def _volatility_segments(scenario_results: dict) -> dict[str, Any]:
    baseline = scenario_results.get("baseline", {})
    high = scenario_results.get("high_spread", {})
    low = scenario_results.get("low_spread", {})
    return {
        "high_spread_vs_baseline": {
            "pf_delta": _delta(high.get("profit_factor"), baseline.get("profit_factor")),
            "dd_delta": _delta(high.get("max_drawdown_pct"), baseline.get("max_drawdown_pct")),
        },
        "low_spread_vs_baseline": {
            "pf_delta": _delta(low.get("profit_factor"), baseline.get("profit_factor")),
        },
    }


def _delta(a, b) -> float | None:
    try:
        return round(float(a) - float(b), 4)
    except (TypeError, ValueError):
        return None


def stress_from_trades(trades: list, window: ValidationWindow) -> dict[str, Any]:
    """Segment trades by regime/volatility proxy."""
    from tradingbot.ml.phase19d.stress_test import run_stress_test
    from tradingbot.ml.research.phase22e.metrics import trades_to_mc_records

    if not trades:
        return run_stress_test([])
    records = trades_to_mc_records(trades) if hasattr(trades[0], "r_multiple") else trades
    return run_stress_test(records)
