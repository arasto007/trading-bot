"""Phase 19C — Monte Carlo stress for filtered trades."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.metrics import expectancy_r, max_drawdown_r, pf_from_r
from tradingbot.ml.phase19c.config import DEFAULT_SEED, MONTE_CARLO_SIMS
from tradingbot.ml.phase19c.filters import apply_profitability_filters, load_filter_settings


def run_montecarlo(trades: list[dict[str, Any]], *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    settings = load_filter_settings()
    pipeline = [t for t in trades if t.get("pipeline_allowed")]
    if not pipeline:
        pipeline = trades

    kept = []
    for t in pipeline:
        features = {"rsi": t.get("rsi", 50), "adx": t.get("adx", 0)}
        if apply_profitability_filters(features, settings=settings).passed:
            kept.append(t)

    r_vals = [float(t["r_multiple"]) for t in kept]
    if len(r_vals) < 10:
        return {
            "phase": "19C",
            "passed": False,
            "reason": "too_few_trades",
            "trades": len(r_vals),
            "n_sims": MONTE_CARLO_SIMS,
        }

    rng = np.random.default_rng(seed)
    fails = 0
    pfs: list[float] = []
    for _ in range(MONTE_CARLO_SIMS):
        sample = rng.permutation(r_vals).tolist()
        slip = rng.uniform(0, 0.1, size=len(sample))
        adjusted = [r - s for r, s in zip(sample, slip)]
        pf = pf_from_r(adjusted)
        pfs.append(pf)
        if pf < 1.0 or expectancy_r(adjusted) < 0:
            fails += 1

    fail_rate = fails / MONTE_CARLO_SIMS
    passed = fail_rate < 0.35 and float(np.mean(pfs)) >= 1.05

    return {
        "phase": "19C",
        "passed": passed,
        "trades": len(r_vals),
        "n_sims": MONTE_CARLO_SIMS,
        "baseline_pf": pf_from_r(r_vals),
        "baseline_exp": expectancy_r(r_vals),
        "baseline_dd": max_drawdown_r(r_vals),
        "mean_pf_stress": round(float(np.mean(pfs)), 4),
        "failure_rate": round(fail_rate, 4),
    }
