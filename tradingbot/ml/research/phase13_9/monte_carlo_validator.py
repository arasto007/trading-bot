"""Phase 13.9 — Monte Carlo stability."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase13_9.config import MONTE_CARLO_SIMS


def run_monte_carlo(trades: list[dict[str, Any]], *, simulations: int = MONTE_CARLO_SIMS, seed: int = 42) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") == "trade"]
    if not executed:
        return {"simulations": simulations, "remains_positive": False, "failure_probability": 1.0}

    r_mults = np.array([float(t.get("R_multiple", 0.0)) for t in executed], dtype=float)
    rng = np.random.default_rng(seed)
    pf_samples = []
    for _ in range(simulations):
        order = rng.permutation(len(r_mults))
        adj = r_mults[order] - rng.uniform(0, 0.05, len(r_mults)) - rng.uniform(0, 0.03, len(r_mults))
        wins = adj[adj > 0].sum()
        losses = abs(adj[adj < 0].sum())
        pf_samples.append(float(wins / losses) if losses > 0 else (2.0 if wins > 0 else 0.0))

    arr = np.array(pf_samples)
    pos = float((arr >= 1.0).mean())
    return {
        "simulations": simulations,
        "trade_count": len(executed),
        "profitable_pct": round(pos, 4),
        "mean_pf": round(float(arr.mean()), 4),
        "failure_probability": round(1.0 - pos, 4),
        "remains_positive": pos >= 0.55,
    }
