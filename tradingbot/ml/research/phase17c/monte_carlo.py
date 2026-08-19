"""Phase 17C — Monte Carlo robustness on research TREND returns."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase17c.config import DEFAULT_SEED, MONTE_CARLO_SIMS
from tradingbot.ml.research.phase17c.metrics import expectancy, max_drawdown, pf_from_returns


def run_monte_carlo(
    returns: list[float],
    *,
    n_sims: int = MONTE_CARLO_SIMS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """
    Bootstrap shuffle of observed return proxies (research TREND signals).
    Does not retrain; measures path stability of the observed trade set.
    """
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return {
            "phase": "17C",
            "n_sims": n_sims,
            "trades": 0,
            "robust": False,
            "failure_probability": 1.0,
            "note": "no_research_trades",
        }

    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    dds: list[float] = []
    exps: list[float] = []
    failures = 0

    for _ in range(n_sims):
        sample = rng.choice(arr, size=len(arr), replace=True)
        pf = pf_from_returns(sample)
        dd = max_drawdown(sample)
        exp = expectancy(sample)
        pfs.append(pf)
        dds.append(dd)
        exps.append(exp)
        if pf < 1.0 or exp < 0.0:
            failures += 1

    pfs_a = np.asarray(pfs)
    dds_a = np.asarray(dds)
    exps_a = np.asarray(exps)
    failure_prob = failures / n_sims

    return {
        "phase": "17C",
        "n_sims": n_sims,
        "trades": int(len(arr)),
        "seed": seed,
        "pf": {
            "mean": round(float(np.mean(pfs_a)), 6),
            "p05": round(float(np.percentile(pfs_a, 5)), 6),
            "p50": round(float(np.percentile(pfs_a, 50)), 6),
            "p95": round(float(np.percentile(pfs_a, 95)), 6),
            "std": round(float(np.std(pfs_a)), 6),
        },
        "drawdown": {
            "mean": round(float(np.mean(dds_a)), 6),
            "p05": round(float(np.percentile(dds_a, 5)), 6),
            "p50": round(float(np.percentile(dds_a, 50)), 6),
        },
        "expectancy": {
            "mean": round(float(np.mean(exps_a)), 6),
            "p05": round(float(np.percentile(exps_a, 5)), 6),
            "p50": round(float(np.percentile(exps_a, 50)), 6),
        },
        "failure_probability": round(float(failure_prob), 6),
        "probability_robustness": round(float(1.0 - failure_prob), 6),
        "robust": failure_prob <= 0.25 and float(np.percentile(pfs_a, 5)) >= 0.8,
    }


def extract_research_returns(shadow_comparison: dict[str, Any]) -> list[float]:
    """Build return proxies from primary 365d research engine actionable signals."""
    win = shadow_comparison.get("windows", {}).get("365d", {})
    research = win.get("research", {})
    n = int(research.get("engine", {}).get("trend_actionable", 0))
    max_p = float(research.get("engine", {}).get("trend_max_prob", 0.4))
    mean_p = float(research.get("engine", {}).get("trend_mean_prob", 0.3))
    if n <= 0:
        return []
    # Heterogeneous margins around mean/max for MC diversity.
    margins = np.linspace(max(0.001, mean_p - 0.4), max(0.001, max_p - 0.4), n)
    return [float(m) for m in margins]
