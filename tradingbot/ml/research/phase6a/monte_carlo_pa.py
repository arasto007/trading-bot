"""Phase 6A — Monte Carlo on PA trade R-multiples."""

from __future__ import annotations

from typing import Any

import numpy as np


def run_monte_carlo_r(
    r_multiples: list[float],
    *,
    simulations: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Shuffle R-multiples; report PF distribution."""
    rs = np.asarray(r_multiples, dtype=float)
    if len(rs) < 5:
        return {
            "simulations": 0,
            "pf_median": 0.0,
            "pf_p5": 0.0,
            "pf_p95": 0.0,
            "expectancy_median": 0.0,
            "worst_5pct_dd_r": 0.0,
        }

    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    dds: list[float] = []

    for _ in range(simulations):
        sample = rng.choice(rs, size=len(rs), replace=True)
        wins = sample[sample > 0]
        losses = sample[sample < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 50.0))
        exps.append(float(sample.mean()))
        eq = peak = mdd = 0.0
        for r in sample:
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        dds.append(mdd)

    pfs_arr = np.asarray(pfs)
    return {
        "simulations": simulations,
        "pf_median": round(float(np.median(pfs_arr)), 3),
        "pf_p5": round(float(np.percentile(pfs_arr, 5)), 3),
        "pf_p95": round(float(np.percentile(pfs_arr, 95)), 3),
        "expectancy_median": round(float(np.median(exps)), 3),
        "worst_5pct_dd_r": round(float(np.percentile(dds, 95)), 2),
        "passes_gate": float(np.median(pfs_arr)) > 1.2,
    }
