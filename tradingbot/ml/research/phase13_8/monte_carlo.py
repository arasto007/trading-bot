"""Phase 13.8 — Monte Carlo robustness for trend trades."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase13_8.config import MONTE_CARLO_SIMS


def run_monte_carlo(
    trades: list[dict[str, Any]],
    *,
    simulations: int = MONTE_CARLO_SIMS,
    seed: int = 42,
) -> dict[str, Any]:
    executed = [t for t in trades if t.get("type") == "trade"]
    if not executed:
        return {
            "simulations": simulations,
            "trade_count": 0,
            "remains_positive": False,
            "failure_probability": 1.0,
        }

    r_mults = np.array([float(t.get("R_multiple", 0.0)) for t in executed], dtype=float)
    rng = np.random.default_rng(seed)
    pf_samples: list[float] = []
    dd_samples: list[float] = []

    for _ in range(simulations):
        order = rng.permutation(len(r_mults))
        adj = r_mults[order] - rng.uniform(0.0, 0.05, len(r_mults)) - rng.uniform(0.0, 0.03, len(r_mults))
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in adj:
            equity += r * 0.005
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
        wins = adj[adj > 0].sum()
        losses = abs(adj[adj < 0].sum())
        pf = float(wins / losses) if losses > 0 else (3.0 if wins > 0 else 0.0)
        pf_samples.append(min(pf, 10.0))
        dd_samples.append(max_dd)

    arr = np.array(pf_samples)
    profitable_pct = float((arr >= 1.0).mean())
    return {
        "phase": "13.8",
        "simulations": simulations,
        "trade_count": len(executed),
        "profitable_pct": round(profitable_pct, 4),
        "mean_pf": round(float(arr.mean()), 4),
        "median_pf": round(float(np.median(arr)), 4),
        "p5_pf": round(float(np.percentile(arr, 5)), 4),
        "p95_pf": round(float(np.percentile(arr, 95)), 4),
        "mean_drawdown": round(float(np.mean(dd_samples)), 4),
        "failure_probability": round(1.0 - profitable_pct, 4),
        "remains_positive": profitable_pct >= 0.55,
        "perturbations": ["spread_increase", "slippage", "trade_sequence_shuffle"],
    }
