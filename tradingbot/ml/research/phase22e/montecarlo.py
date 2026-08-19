"""Phase 22E — Monte Carlo on trade order, spread, slippage, missing trades, latency."""

from __future__ import annotations

from typing import Any

from tradingbot.backtest.models import ClosedTrade
from tradingbot.ml.phase19a.robustness import run_robustness
from tradingbot.ml.research.phase22e.config import DEFAULT_SEED, MONTE_CARLO_SIMS
from tradingbot.ml.research.phase22e.metrics import trades_to_mc_records


def run_monte_carlo(trades: list[ClosedTrade], *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    records = trades_to_mc_records(trades)
    if not records:
        return {
            "phase": "22E",
            "passed": False,
            "note": "no_trades",
            "n_sims": MONTE_CARLO_SIMS,
            "scenarios": {},
        }
    result = run_robustness(records, seed=seed)
    result["phase"] = "22E"
    result["n_sims"] = MONTE_CARLO_SIMS
    required = (
        "random_trade_order",
        "random_spread",
        "random_slippage",
        "missing_trades",
        "execution_delay",
    )
    scenarios = result.get("scenarios", {})
    scenario_pass = all(
        scenarios.get(s, {}).get("failure_rate", 1.0) < 0.40
        for s in required
        if s in scenarios
    )
    result["scenario_pass"] = scenario_pass
    result["passed"] = bool(result.get("passed")) and scenario_pass
    return result
