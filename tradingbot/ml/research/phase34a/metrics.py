"""Phase 34A — statistics from replayed R-multiples (research only)."""

from __future__ import annotations

import math
from typing import Any


def _pf(rs: list[float]) -> float:
    w = sum(x for x in rs if x > 0)
    l = abs(sum(x for x in rs if x < 0))
    if l > 0:
        return round(w / l, 4)
    return 2.0 if w > 0 else 0.0


def _max_drawdown(equity: list[float]) -> tuple[float, float]:
    peak = -float("inf")
    max_dd_pct = 0.0
    max_dd_abs = 0.0
    for eq in equity:
        peak = max(peak, eq)
        if peak > 0:
            dd_abs = peak - eq
            dd_pct = dd_abs / peak * 100
            max_dd_abs = max(max_dd_abs, dd_abs)
            max_dd_pct = max(max_dd_pct, dd_pct)
    return round(max_dd_pct, 2), round(max_dd_abs, 4)


def _sharpe_from_equity(equity: list[float], trades_per_year: float = 252 * 24 * 12) -> float:
    if len(equity) < 3:
        return 0.0
    rets = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev != 0:
            rets.append((equity[i] - prev) / prev)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    per_trade = trades_per_year / max(len(rets), 1)
    return round(mean / std * math.sqrt(per_trade), 4)


def stats_from_replays(
    replays: list[dict[str, Any]],
    *,
    initial_balance: float = 200.0,
    risk_pct: float = 0.5,
    timeframe: str = "M5",
) -> dict[str, Any]:
    """Compute WR, PF, expectancy, Sharpe, avg R, holding time, max DD from replay list."""
    rs = [float(r.get("r_multiple", 0)) for r in replays]
    n = len(rs)
    if n == 0:
        return {
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "expectancy_dollars": 0.0,
            "sharpe_ratio": 0.0,
            "average_r": 0.0,
            "avg_holding_bars": 0.0,
            "avg_holding_minutes": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_abs": 0.0,
            "wins": 0,
            "losses": 0,
        }

    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    risk_unit = initial_balance * (risk_pct / 100.0)
    equity = [initial_balance]
    for r in rs:
        equity.append(equity[-1] + r * risk_unit)

    holding_bars = []
    bar_minutes = {"M5": 5, "M15": 15, "H4": 240}.get(timeframe.upper(), 5)
    for r in replays:
        b = r.get("bars_to_tp") or r.get("bars_to_sl")
        if b is None and r.get("exit_reason") == "timeout":
            b = 500
        if b is not None:
            holding_bars.append(float(b))

    max_dd_pct, max_dd_abs = _max_drawdown(equity)
    avg_r = round(sum(rs) / n, 4)
    exp_r = avg_r
    exp_dollars = round(exp_r * risk_unit, 4)

    return {
        "trade_count": n,
        "win_rate_pct": round(len(wins) / n * 100, 2),
        "profit_factor": _pf(rs),
        "expectancy_r": exp_r,
        "expectancy_dollars": exp_dollars,
        "sharpe_ratio": _sharpe_from_equity(equity),
        "average_r": avg_r,
        "avg_holding_bars": round(sum(holding_bars) / max(len(holding_bars), 1), 2),
        "avg_holding_minutes": round(sum(holding_bars) / max(len(holding_bars), 1) * bar_minutes, 2),
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_abs": max_dd_abs,
        "wins": len(wins),
        "losses": len(losses),
        "gross_r_wins": round(sum(wins), 4),
        "gross_r_losses": round(abs(sum(losses)), 4),
    }


def classify_ml_quality(stats: dict[str, Any]) -> str:
    """Classify intrinsic ML quality from raw replay stats only."""
    pf = float(stats.get("profit_factor", 0))
    wr = float(stats.get("win_rate_pct", 0))
    exp = float(stats.get("expectancy_r", 0))
    n = int(stats.get("trade_count", 0))

    if n < 10:
        return "UNUSABLE"
    if pf >= 1.5 and wr >= 55 and exp > 0.15:
        return "ML_IS_EXCELLENT"
    if pf >= 1.2 and wr >= 50 and exp > 0.05:
        return "ML_IS_GOOD"
    if pf >= 1.0 and wr >= 45 and exp >= 0:
        return "ML_IS_AVERAGE"
    if pf >= 0.8:
        return "ML_IS_WEAK"
    return "ML_IS_UNUSABLE"


def confidence_bucket(conf: float, step: float = 0.05) -> str:
    c = max(0.0, min(1.0, float(conf)))
    if c < 0.40:
        return "<0.40"
    low = 0.40
    while low < 0.95:
        hi = round(low + step, 2)
        if low <= c < hi:
            return f"{low:.2f}-{hi:.2f}"
        low = hi
    return "0.95-1.00"
