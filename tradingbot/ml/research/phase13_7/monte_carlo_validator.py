"""Phase 13.7 — Monte Carlo robustness simulation."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase13_7.config import MONTE_CARLO_SIMULATIONS


def _executed_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in trades if t.get("type") == "trade"]


def run_monte_carlo(
    trades: list[dict[str, Any]],
    *,
    simulations: int = MONTE_CARLO_SIMULATIONS,
    seed: int = 42,
) -> dict[str, Any]:
    executed = _executed_trades(trades)
    if not executed:
        return {
            "phase": "13.7",
            "simulations": simulations,
            "trade_count": 0,
            "profitable_pct": 0.0,
            "mean_pf": 0.0,
            "median_pf": 0.0,
            "remains_profitable": False,
            "shuffle": True,
        }

    r_mults = np.array([float(t.get("R_multiple", 0.0)) for t in executed], dtype=float)
    rng = np.random.default_rng(seed)
    pf_samples: list[float] = []

    for _ in range(simulations):
        order = rng.permutation(len(r_mults))
        shuffled = r_mults[order]
        # spread increase, slippage, execution delay noise
        spread_penalty = rng.uniform(0.0, 0.05, size=len(shuffled))
        slippage = rng.uniform(0.0, 0.03, size=len(shuffled))
        delay_skip = rng.random(size=len(shuffled)) < 0.02
        adjusted = shuffled - spread_penalty - slippage
        adjusted = np.where(delay_skip, 0.0, adjusted)

        wins = adjusted[adjusted > 0].sum()
        losses = abs(adjusted[adjusted < 0].sum())
        pf = float(wins / losses) if losses > 0 else (3.0 if wins > 0 else 0.0)
        pf_samples.append(min(pf, 10.0))

    arr = np.array(pf_samples)
    profitable_pct = float((arr >= 1.0).mean())
    return {
        "phase": "13.7",
        "simulations": simulations,
        "trade_count": len(executed),
        "profitable_pct": round(profitable_pct, 4),
        "mean_pf": round(float(arr.mean()), 4),
        "median_pf": round(float(np.median(arr)), 4),
        "p5_pf": round(float(np.percentile(arr, 5)), 4),
        "p95_pf": round(float(np.percentile(arr, 95)), 4),
        "remains_profitable": profitable_pct >= 0.55,
        "perturbations": ["trade_sequence_shuffle", "spread_increase", "slippage", "execution_delay"],
        "shuffle": True,
    }
