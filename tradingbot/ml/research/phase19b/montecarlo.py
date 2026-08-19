"""Phase 19B — Monte Carlo stress for surviving candidates."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from tradingbot.ml.phase19a.metrics import expectancy_r, max_drawdown_r, pf_from_r
from tradingbot.ml.research.phase19b.config import DEFAULT_SEED, MONTE_CARLO_SIMS
from tradingbot.ml.research.phase19b.walkforward import _rebuild_filter, _train_percentile_filter


def _filter_trades(name: str, trades: list[dict]) -> list[dict]:
    fn = _rebuild_filter(name)
    if fn is None:
        fn = _train_percentile_filter(name, trades)
    if fn is None:
        return trades
    return [t for t in trades if fn(t)]


def stress_candidate(name: str, trades: list[dict], *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    kept = _filter_trades(name, trades)
    r_vals = [float(t["r_multiple"]) for t in kept]
    if len(r_vals) < 10:
        return {"name": name, "passed": False, "reason": "too_few_trades", "trades": len(r_vals)}

    rng = np.random.default_rng(seed)
    n = MONTE_CARLO_SIMS
    fails = 0
    pfs = []
    for _ in range(n):
        # shuffle + mild slippage
        sample = rng.permutation(r_vals).tolist()
        slip = rng.uniform(0, 0.1, size=len(sample))
        adjusted = [r - s for r, s in zip(sample, slip)]
        pf = pf_from_r(adjusted)
        pfs.append(pf)
        if pf < 1.0 or expectancy_r(adjusted) < 0:
            fails += 1

    fail_rate = fails / n
    return {
        "name": name,
        "passed": fail_rate < 0.35 and float(np.mean(pfs)) >= 1.05,
        "trades": len(r_vals),
        "baseline_pf": pf_from_r(r_vals),
        "baseline_exp": expectancy_r(r_vals),
        "baseline_dd": max_drawdown_r(r_vals),
        "mean_pf_stress": round(float(np.mean(pfs)), 4),
        "failure_rate": round(fail_rate, 4),
    }


def run_montecarlo(trades: list[dict], survivor_names: list[str]) -> dict[str, Any]:
    results = [stress_candidate(n, trades) for n in survivor_names]
    passed = [r for r in results if r.get("passed")]
    return {
        "phase": "19B",
        "n_sims": MONTE_CARLO_SIMS,
        "tested": results,
        "passed": passed,
        "failed": [r for r in results if not r.get("passed")],
    }
