"""Phase 13.10 — Monte Carlo validation (95% profitable gate)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase13_10.config import MIN_MONTE_CARLO_PROFITABLE, MONTE_CARLO_SIMS


def run_monte_carlo_phase13_10(
    trades: list[dict[str, Any]],
    *,
    simulations: int = MONTE_CARLO_SIMS,
    seed: int = 42,
) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") == "trade"]
    if not executed:
        return {
            "phase": "13.10",
            "simulations": simulations,
            "trade_count": 0,
            "profitable_pct": 0.0,
            "passes_gate": False,
            "rejection_reason": "no_trades",
        }

    r_mults = np.array([float(t.get("R_multiple", 0.0)) for t in executed], dtype=float)
    rng = np.random.default_rng(seed)
    pf_samples: list[float] = []
    dd_samples: list[float] = []
    exp_samples: list[float] = []

    for _ in range(simulations):
        order = rng.permutation(len(r_mults))
        shuffled = r_mults[order]
        noise = rng.uniform(0, 0.05, len(shuffled)) + rng.uniform(0, 0.03, len(shuffled))
        adj = shuffled - noise
        wins = adj[adj > 0].sum()
        losses = abs(adj[adj < 0].sum())
        pf = float(wins / losses) if losses > 0 else (2.0 if wins > 0 else 0.0)
        pf_samples.append(pf)
        exp_samples.append(float(adj.mean()))
        equity = np.cumsum(adj)
        peak = np.maximum.accumulate(equity)
        dd = float((peak - equity).max()) if len(equity) else 0.0
        dd_samples.append(dd)

    pf_arr = np.array(pf_samples)
    profitable_pct = float((pf_arr >= 1.0).mean())
    passes = profitable_pct >= MIN_MONTE_CARLO_PROFITABLE

    return {
        "phase": "13.10",
        "simulations": simulations,
        "seed": seed,
        "trade_count": len(executed),
        "profitable_pct": round(profitable_pct, 4),
        "pf_distribution": {
            "mean": round(float(pf_arr.mean()), 4),
            "std": round(float(pf_arr.std()), 4),
            "p05": round(float(np.percentile(pf_arr, 5)), 4),
            "p50": round(float(np.percentile(pf_arr, 50)), 4),
            "p95": round(float(np.percentile(pf_arr, 95)), 4),
        },
        "drawdown_distribution": {
            "mean": round(float(np.mean(dd_samples)), 4),
            "p95": round(float(np.percentile(dd_samples, 95)), 4),
        },
        "expectancy_distribution": {
            "mean": round(float(np.mean(exp_samples)), 4),
            "std": round(float(np.std(exp_samples)), 4),
        },
        "min_profitable_pct_required": MIN_MONTE_CARLO_PROFITABLE,
        "passes_gate": passes,
        "rejection_reason": None if passes else "profitable_simulations_below_95pct",
    }
