"""Phase 17C — performance metric helpers."""

from __future__ import annotations

from typing import Any

import numpy as np


def pf_from_returns(returns: list[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    gains = float(arr[arr > 0].sum())
    losses = float(-arr[arr < 0].sum())
    if losses <= 0:
        return 2.0 if gains > 0 else 0.0
    return round(gains / losses, 6)


def expectancy(returns: list[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    return round(float(np.mean(arr)), 6) if len(arr) else 0.0


def max_drawdown(returns: list[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    return round(float(np.min(dd)), 6)


def win_rate(returns: list[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    return round(float(np.mean(arr > 0)), 6)


def sharpe_proxy(returns: list[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    std = float(np.std(arr))
    if std < 1e-12:
        return 0.0
    return round(float(np.mean(arr) / std), 6)


def sortino_proxy(returns: list[float] | np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return 0.0
    downside = arr[arr < 0]
    if len(downside) == 0:
        return 2.0 if float(np.mean(arr)) > 0 else 0.0
    dstd = float(np.std(downside))
    if dstd < 1e-12:
        return 0.0
    return round(float(np.mean(arr) / dstd), 6)


def summarize_returns(returns: list[float] | np.ndarray) -> dict[str, Any]:
    arr = np.asarray(returns, dtype=float)
    return {
        "trades": int(len(arr)),
        "pf": pf_from_returns(arr),
        "expectancy": expectancy(arr),
        "drawdown": max_drawdown(arr),
        "win_rate": win_rate(arr),
        "sharpe": sharpe_proxy(arr),
        "sortino": sortino_proxy(arr),
        "mean_duration_proxy": 1.0,  # bar-level proxy (1 stride unit)
    }
