"""Phase 1B — extended PA+Meta backtest metrics + Monte Carlo on R-multiples."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from tradingbot.backtest.models import BacktestResult, ClosedTrade


def _pf_from_rs(rs: list[float]) -> float:
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    if gl <= 0:
        return 999.0 if gw > 0 else 0.0
    return gw / gl


def extract_window_metrics(result: BacktestResult) -> dict[str, Any]:
    trades: list[ClosedTrade] = result.trades
    if not trades:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "max_drawdown_R": 0.0,
            "sharpe": 0.0,
            "longest_loss_streak": 0,
            "average_hold_bars": 0.0,
        }

    rs = [float(t.r_multiple) for t in trades]
    wins = sum(1 for r in rs if r > 0)
    pf = _pf_from_rs(rs)

    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)

    streak = longest = 0
    for r in rs:
        if r < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0

    hold_bars: list[float] = []
    for t in trades:
        if t.entry_time and t.exit_time:
            delta = (t.exit_time - t.entry_time).total_seconds() / 300.0  # M5
            if delta > 0:
                hold_bars.append(delta)

    sharpe = _sharpe_r(rs)

    pf_out: Any = round(pf, 3) if pf != 999.0 else "inf"
    return {
        "trades": len(trades),
        "win_rate": round(wins / len(rs) * 100, 2),
        "profit_factor": pf_out,
        "expectancy_R": round(sum(rs) / len(rs), 3),
        "max_drawdown_R": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "longest_loss_streak": longest,
        "average_hold_bars": round(sum(hold_bars) / len(hold_bars), 1) if hold_bars else 0.0,
    }


def _sharpe_r(rs: list[float]) -> float:
    if len(rs) < 2:
        return 0.0
    arr = np.asarray(rs, dtype=float)
    std = float(arr.std(ddof=1))
    if std <= 1e-12:
        return 0.0
    return float(arr.mean() / std * math.sqrt(len(arr)))


def run_monte_carlo_r(
    trades: list[ClosedTrade],
    *,
    simulations: int = 10_000,
    seed: int = 42,
    ruin_threshold_r: float = -6.0,
) -> dict[str, Any]:
    """10k shuffle on R-multiples — PF, expectancy, worst 5% DD (R), ruin probability."""
    rs = np.asarray([float(t.r_multiple) for t in trades], dtype=float)
    if len(rs) < 5:
        return {
            "simulations": 0,
            "median_PF": 0.0,
            "median_expectancy": 0.0,
            "worst_5pct_drawdown_R": 0.0,
            "probability_of_ruin": 100.0,
        }

    rng = np.random.default_rng(seed)
    pfs: list[float] = []
    exps: list[float] = []
    dds: list[float] = []
    ruined = 0

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
        if eq <= ruin_threshold_r:
            ruined += 1

    return {
        "simulations": simulations,
        "median_PF": round(float(np.median(pfs)), 3),
        "median_expectancy": round(float(np.median(exps)), 3),
        "worst_5pct_drawdown_R": round(float(np.percentile(dds, 95)), 2),
        "probability_of_ruin": round(ruined / simulations * 100, 2),
    }


def passes_phase1b_window(metrics: dict[str, Any]) -> bool:
    pf = metrics.get("profit_factor", 0)
    pf_num = 999.0 if pf == "inf" else float(pf)
    return (
        pf_num > 1.5
        and float(metrics.get("expectancy_R", 0)) > 0.4
        and float(metrics.get("max_drawdown_R", 999)) < 6.0
    )


def passes_phase1b_mc(mc: dict[str, Any]) -> bool:
    return (
        float(mc.get("median_PF", 0)) > 1.3
        and float(mc.get("probability_of_ruin", 100)) < 5.0
    )
