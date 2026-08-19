"""Phase 19A — performance metric helpers."""

from __future__ import annotations

from typing import Any

import numpy as np


def pf_from_r(r_values: list[float] | np.ndarray) -> float:
    arr = np.asarray(r_values, dtype=float)
    if len(arr) == 0:
        return 0.0
    gains = float(arr[arr > 0].sum())
    losses = float(-arr[arr < 0].sum())
    if losses <= 0:
        return 2.0 if gains > 0 else 0.0
    return round(gains / losses, 6)


def expectancy_r(r_values: list[float] | np.ndarray) -> float:
    arr = np.asarray(r_values, dtype=float)
    return round(float(np.mean(arr)), 6) if len(arr) else 0.0


def max_drawdown_r(r_values: list[float] | np.ndarray) -> float:
    arr = np.asarray(r_values, dtype=float)
    if len(arr) == 0:
        return 0.0
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    return round(float(np.min(equity - peak)), 6)


def sharpe_r(r_values: list[float] | np.ndarray) -> float:
    arr = np.asarray(r_values, dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr))
    return round(float(np.mean(arr) / std), 6) if std > 1e-12 else 0.0


def sortino_r(r_values: list[float] | np.ndarray) -> float:
    arr = np.asarray(r_values, dtype=float)
    if len(arr) < 2:
        return 0.0
    downside = arr[arr < 0]
    if len(downside) == 0:
        return 2.0 if float(np.mean(arr)) > 0 else 0.0
    dstd = float(np.std(downside))
    return round(float(np.mean(arr) / dstd), 6) if dstd > 1e-12 else 0.0


def calmar_r(r_values: list[float] | np.ndarray) -> float:
    arr = np.asarray(r_values, dtype=float)
    if len(arr) == 0:
        return 0.0
    ann_return = float(np.sum(arr)) / max(len(arr) / 252, 1)  # proxy annualized from R-bars
    dd = abs(max_drawdown_r(arr))
    return round(ann_return / dd, 6) if dd > 1e-12 else 0.0


def consecutive_streaks(r_values: list[float]) -> dict[str, int]:
    max_w = max_l = cur_w = cur_l = 0
    for r in r_values:
        if r > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        elif r < 0:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
        else:
            cur_w = cur_l = 0
    return {"max_consecutive_wins": max_w, "max_consecutive_losses": max_l}


def compute_performance(trades: list[dict[str, Any]], *, risk_per_trade: float = 0.005) -> dict[str, Any]:
    """Aggregate performance from accepted trade records (R-multiples)."""
    accepted = [t for t in trades if t.get("allowed")]
    r_vals = [float(t["r_multiple"]) for t in accepted]
    wins = [r for r in r_vals if r > 0]
    losses = [r for r in r_vals if r < 0]
    dollar = [r * risk_per_trade for r in r_vals]

    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net = gross_profit + gross_loss
    dd = max_drawdown_r(r_vals)
    streaks = consecutive_streaks(r_vals)
    durations = [int(t.get("duration_bars", 0)) for t in accepted if t.get("duration_bars")]

    recovery = round(net / abs(dd), 6) if dd < -1e-12 else 0.0

    return {
        "trades": len(accepted),
        "net_profit_r": round(net, 4),
        "gross_profit_r": round(gross_profit, 4),
        "gross_loss_r": round(gross_loss, 4),
        "net_profit_pct": round(sum(dollar) * 100, 4),
        "profit_factor": pf_from_r(r_vals),
        "expectancy_r": expectancy_r(r_vals),
        "recovery_factor": recovery,
        "sharpe": sharpe_r(r_vals),
        "sortino": sortino_r(r_vals),
        "calmar": calmar_r(r_vals),
        "win_rate": round(len(wins) / len(r_vals), 6) if r_vals else 0.0,
        "average_win_r": round(float(np.mean(wins)), 6) if wins else 0.0,
        "average_loss_r": round(float(np.mean(losses)), 6) if losses else 0.0,
        "average_holding_bars": round(float(np.mean(durations)), 2) if durations else 0.0,
        "maximum_drawdown_r": dd,
        **streaks,
    }
