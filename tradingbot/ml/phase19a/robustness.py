"""Phase 19A — robustness (Monte Carlo + stress)."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.phase19a.config import DEFAULT_SEED, MONTE_CARLO_SIMS
from tradingbot.ml.phase19a.metrics import expectancy_r, max_drawdown_r, pf_from_r


def _accepted_r(trades: list[dict[str, Any]]) -> list[float]:
    return [float(t["r_multiple"]) for t in trades if t.get("allowed")]


def run_robustness(trades: list[dict[str, Any]], *, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    r_vals = _accepted_r(trades)
    if not r_vals:
        return {"phase": "19A", "passed": False, "note": "no_trades"}

    rng = np.random.default_rng(seed)
    n = MONTE_CARLO_SIMS
    results: dict[str, Any] = {}

    # Random trade order
    order_pfs, order_fail = [], 0
    for _ in range(n):
        shuffled = rng.permutation(r_vals).tolist()
        pf = pf_from_r(shuffled)
        order_pfs.append(pf)
        if pf < 1.0:
            order_fail += 1
    results["random_trade_order"] = {
        "mean_pf": round(float(np.mean(order_pfs)), 4),
        "failure_rate": round(order_fail / n, 4),
    }

    # Random spread (reduce R by 0-0.15)
    spread_pfs, spread_fail = [], 0
    for _ in range(n):
        penalty = rng.uniform(0, 0.15, size=len(r_vals))
        adjusted = [r - p for r, p in zip(r_vals, penalty)]
        pf = pf_from_r(adjusted)
        spread_pfs.append(pf)
        if pf < 1.0:
            spread_fail += 1
    results["random_spread"] = {
        "mean_pf": round(float(np.mean(spread_pfs)), 4),
        "failure_rate": round(spread_fail / n, 4),
    }

    # Random slippage
    slip_pfs, slip_fail = [], 0
    for _ in range(n):
        slip = rng.uniform(0, 0.1, size=len(r_vals))
        adjusted = [r - s for r, s in zip(r_vals, slip)]
        pf = pf_from_r(adjusted)
        slip_pfs.append(pf)
        if pf < 1.0:
            slip_fail += 1
    results["random_slippage"] = {
        "mean_pf": round(float(np.mean(slip_pfs)), 4),
        "failure_rate": round(slip_fail / n, 4),
    }

    # Missing trades (drop 10-30%)
    miss_pfs, miss_fail = [], 0
    for _ in range(n):
        keep = rng.random(len(r_vals)) > rng.uniform(0.1, 0.3)
        subset = [r for r, k in zip(r_vals, keep) if k]
        if len(subset) < 5:
            continue
        pf = pf_from_r(subset)
        miss_pfs.append(pf)
        if pf < 1.0:
            miss_fail += 1
    results["missing_trades"] = {
        "mean_pf": round(float(np.mean(miss_pfs)), 4) if miss_pfs else 0.0,
        "failure_rate": round(miss_fail / max(len(miss_pfs), 1), 4),
    }

    # Execution delay (shift last 5% to loss)
    delay_pfs, delay_fail = [], 0
    for _ in range(n):
        adjusted = list(r_vals)
        n_delay = max(1, int(len(adjusted) * 0.05))
        idx = rng.choice(len(adjusted), size=n_delay, replace=False)
        for i in idx:
            adjusted[i] = min(adjusted[i], -0.2)
        pf = pf_from_r(adjusted)
        delay_pfs.append(pf)
        if pf < 1.0:
            delay_fail += 1
    results["execution_delay"] = {
        "mean_pf": round(float(np.mean(delay_pfs)), 4),
        "failure_rate": round(delay_fail / n, 4),
    }

    baseline_pf = pf_from_r(r_vals)
    baseline_exp = expectancy_r(r_vals)
    baseline_dd = max_drawdown_r(r_vals)

    max_fail_rate = max(
        results["random_trade_order"]["failure_rate"],
        results["random_spread"]["failure_rate"],
        results["random_slippage"]["failure_rate"],
    )
    passed = baseline_pf >= 1.0 and baseline_exp > 0 and max_fail_rate < 0.35

    return {
        "phase": "19A",
        "passed": passed,
        "n_sims": n,
        "seed": seed,
        "baseline_pf": baseline_pf,
        "baseline_expectancy": baseline_exp,
        "baseline_max_drawdown_r": baseline_dd,
        "scenarios": results,
        "max_failure_rate": round(max_fail_rate, 4),
    }
