"""Phase 14.5 — Monte Carlo robustness validation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase14_5.config import MIN_MC_PROFITABLE, MONTE_CARLO_SIMS


def run_monte_carlo_validation(
    records: list[dict[str, Any]],
    *,
    simulations: int = MONTE_CARLO_SIMS,
    seed: int = 42,
) -> dict[str, Any]:
    accepted = [r for r in records if r.get("allowed")]
    r_mults = np.array([float(r["r_multiple"]) for r in accepted], dtype=float)

    if len(r_mults) == 0:
        return {
            "phase": "14.5",
            "simulations": simulations,
            "trade_count": 0,
            "profitable_pct": 0.0,
            "passes_gate": False,
        }

    rng = np.random.default_rng(seed)
    pf_samples: list[float] = []
    dd_samples: list[float] = []

    for _ in range(simulations):
        order = rng.permutation(len(r_mults))
        adj = r_mults[order] - rng.uniform(0, 0.03, len(r_mults))
        wins = adj[adj > 0].sum()
        losses = abs(adj[adj < 0].sum())
        pf_samples.append(float(wins / losses) if losses > 0 else (2.0 if wins > 0 else 0.0))
        equity = np.cumsum(adj)
        peak = np.maximum.accumulate(equity)
        dd_samples.append(float((peak - equity).max()) if len(equity) else 0.0)

    pf_arr = np.array(pf_samples)
    profitable_pct = float((pf_arr >= 1.0).mean())

    return {
        "phase": "14.5",
        "simulations": simulations,
        "seed": seed,
        "trade_count": len(accepted),
        "profitable_pct": round(profitable_pct, 4),
        "pf_distribution": {
            "mean": round(float(pf_arr.mean()), 4),
            "std": round(float(pf_arr.std()), 4),
            "p05": round(float(np.percentile(pf_arr, 5)), 4),
            "p95": round(float(np.percentile(pf_arr, 95)), 4),
        },
        "drawdown_distribution": {
            "mean": round(float(np.mean(dd_samples)), 4),
            "p95": round(float(np.percentile(dd_samples, 95)), 4),
        },
        "passes_gate": profitable_pct >= MIN_MC_PROFITABLE,
    }
