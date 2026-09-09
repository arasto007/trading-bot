"""Phase 1.5.39 — walk-forward + Monte Carlo on REAL R-multiples only."""

from __future__ import annotations

from typing import Any

import numpy as np

from tradingbot.ml.research.v41_isolated.replay import MIN_TRADES_FOR_INFERENCE, summarize_r

DEFAULT_MC_PATHS = 2000
MIN_OOS_FOR_WF = 30
MIN_TRADES_FOR_MC = 30


def walk_forward_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Time-ordered OOS folds after freeze. In-sample years are labeled, not valid WF."""
    oos = [t for t in trades if t.get("split") == "oos"]
    if len(oos) < MIN_OOS_FOR_WF:
        return {
            "status": "INSUFFICIENT",
            "reason": (
                f"OOS trades={len(oos)} < {MIN_OOS_FOR_WF}. "
                "Frozen v41 was trained through 2025-08-18; 2024/2025 folds would be in-sample."
            ),
            "oos_trades": len(oos),
            "folds": [],
            "aggregate": summarize_r([t["r_multiple"] for t in oos]),
        }

    folds: list[dict[str, Any]] = []
    by_year: dict[str, list[float]] = {}
    for t in oos:
        year = str(t["timestamp"])[:4]
        by_year.setdefault(year, []).append(float(t["r_multiple"]))
    for year in sorted(by_year):
        folds.append({"fold": f"oos_{year}", "train_leak": False, **summarize_r(by_year[year])})
    return {
        "status": "OK" if all(f["trades"] >= 5 for f in folds) else "THIN_FOLDS",
        "reason": None,
        "oos_trades": len(oos),
        "folds": folds,
        "aggregate": summarize_r([t["r_multiple"] for t in oos]),
    }


def monte_carlo_r(
    returns: list[float],
    *,
    n_paths: int = DEFAULT_MC_PATHS,
    seed: int = 42,
    ruin_threshold_r: float = -20.0,
) -> dict[str, Any]:
    arr = np.asarray(returns, dtype=float)
    n = int(len(arr))
    if n < MIN_TRADES_FOR_MC:
        return {
            "status": "INSUFFICIENT",
            "reason": f"trades={n} < {MIN_TRADES_FOR_MC}; will not manufacture confidence",
            "n_trades": n,
            "pseudo_return": False,
        }
    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    dds: list[float] = []
    terminal: list[float] = []
    ruin = 0
    loss_paths = 0
    for _ in range(n_paths):
        path = rng.choice(arr, size=n, replace=True)
        eq = np.cumsum(path)
        terminal.append(float(eq[-1]))
        if eq[-1] < 0:
            loss_paths += 1
        peak = np.maximum.accumulate(eq)
        dd = float(np.min(eq - peak))
        dds.append(dd)
        if dd <= ruin_threshold_r or float(eq.min()) <= ruin_threshold_r:
            ruin += 1
        gains = float(path[path > 0].sum())
        loss_abs = float(-path[path < 0].sum())
        pfs.append(float("inf") if loss_abs <= 0 else gains / loss_abs)
        exps.append(float(path.mean()))
    finite_pf = [p for p in pfs if np.isfinite(p)]
    return {
        "status": "OK",
        "n_trades": n,
        "n_paths": n_paths,
        "seed": seed,
        "pseudo_return": False,
        "profit_factor": _pct(finite_pf),
        "expectancy": _pct(exps),
        "max_drawdown_r": _pct(dds),
        "terminal_r": _pct(terminal),
        "probability_of_loss": round(loss_paths / n_paths, 6),
        "probability_of_ruin": round(ruin / n_paths, 6),
        "ruin_threshold_r": ruin_threshold_r,
        "meaningful": n >= MIN_TRADES_FOR_INFERENCE,
    }


def _pct(values: list[float]) -> dict[str, float]:
    a = np.asarray(values, dtype=float)
    return {
        "p05": round(float(np.percentile(a, 5)), 6),
        "p25": round(float(np.percentile(a, 25)), 6),
        "p50": round(float(np.percentile(a, 50)), 6),
        "p75": round(float(np.percentile(a, 75)), 6),
        "p95": round(float(np.percentile(a, 95)), 6),
        "mean": round(float(a.mean()), 6),
    }
