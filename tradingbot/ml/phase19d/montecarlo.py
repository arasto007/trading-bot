"""Phase 19D — Monte Carlo certification (full scenario suite)."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.robustness import run_robustness


def run_montecarlo_certification(trades: list[dict[str, Any]], *, seed: int = 42) -> dict[str, Any]:
    """Run random order, spread, slippage, missing trades, execution delay."""
    result = run_robustness(trades, seed=seed)
    result["phase"] = "19D"
    scenarios = result.get("scenarios", {})
    required = (
        "random_trade_order",
        "random_spread",
        "random_slippage",
        "missing_trades",
        "execution_delay",
    )
    scenario_pass = all(
        scenarios.get(s, {}).get("failure_rate", 1.0) < 0.35
        for s in required
    )
    result["scenario_pass"] = scenario_pass
    result["passed"] = bool(result.get("passed")) and scenario_pass
    return result
