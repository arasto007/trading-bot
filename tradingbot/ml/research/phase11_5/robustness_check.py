"""Phase 11.5 — bootstrap and Monte Carlo robustness checks."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.phase11_5._metrics import trade_metrics


def run_robustness_check(
    trades: list[dict[str, Any]],
    *,
    iterations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    if not trades:
        return {"iterations": 0, "note": "no trades"}

    rng = np.random.default_rng(seed)
    rs = np.array([float(t.get("R_multiple", 0)) for t in trades], dtype=np.float64)
    pnls = np.array([float(t.get("pnl", 0)) for t in trades], dtype=np.float64)

    boot_pf: list[float] = []
    boot_exp: list[float] = []
    boot_dd: list[float] = []
    mc_equity: list[float] = []

    n = len(trades)
    for _ in range(iterations):
        idx = rng.integers(0, n, size=n)
        sample = [trades[i] for i in idx]
        m = trade_metrics(sample)
        boot_pf.append(m["profit_factor"])
        boot_exp.append(m["expectancy_r"])
        boot_dd.append(m["max_drawdown"])

        shuffled_rs = rs[rng.permutation(n)]
        eq = 10_000.0
        for r in shuffled_rs:
            eq += float(r) * eq * 0.005
        mc_equity.append(eq)

    return {
        "iterations": iterations,
        "bootstrap": {
            "profit_factor": _ci(boot_pf),
            "expectancy_r": _ci(boot_exp),
            "max_drawdown": _ci(boot_dd),
        },
        "monte_carlo_equity": {
            "mean_final_equity": round(float(np.mean(mc_equity)), 2),
            "p5_final_equity": round(float(np.percentile(mc_equity, 5)), 2),
            "p95_final_equity": round(float(np.percentile(mc_equity, 95)), 2),
        },
        "confidence_level": _confidence_label(boot_pf, boot_exp),
    }


def _ci(samples: list[float]) -> dict[str, float]:
    arr = np.array(samples, dtype=np.float64)
    return {
        "mean": round(float(arr.mean()), 4),
        "p5": round(float(np.percentile(arr, 5)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
    }


def _confidence_label(pf_samples: list[float], exp_samples: list[float]) -> str:
    pf_pos = sum(1 for x in pf_samples if x >= 1.0) / len(pf_samples)
    exp_pos = sum(1 for x in exp_samples if x >= 0) / len(exp_samples)
    if pf_pos >= 0.8 and exp_pos >= 0.8:
        return "HIGH"
    if pf_pos >= 0.6 and exp_pos >= 0.6:
        return "MEDIUM"
    return "LOW"
