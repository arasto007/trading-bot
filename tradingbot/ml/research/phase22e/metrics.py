"""Phase 22E — extended profitability metrics for certification."""

from __future__ import annotations

import math
from typing import Any

from tradingbot.backtest.metrics import compute_metrics, _BARS_PER_YEAR, _max_drawdown
from tradingbot.backtest.models import BacktestResult, ClosedTrade


def _sortino(equity_curve: list[dict], timeframe: str) -> float:
    eqs = [p.get("equity", 0.0) for p in equity_curve]
    if len(eqs) < 3:
        return 0.0
    returns = []
    for i in range(1, len(eqs)):
        prev = eqs[i - 1]
        if prev != 0:
            returns.append((eqs[i] - prev) / prev)
    downside = [r for r in returns if r < 0]
    if len(downside) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum(r * r for r in downside) / len(downside)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    ann = math.sqrt(_BARS_PER_YEAR.get(timeframe.upper(), 252 * 24 * 12))
    return mean / std * ann


def _average_r(trades: list[ClosedTrade]) -> float:
    rs = [t.r_multiple for t in trades if t.r_multiple != 0]
    return round(sum(rs) / len(rs), 4) if rs else 0.0


def _recovery_factor(net_profit: float, max_dd_abs: float) -> float:
    if max_dd_abs <= 0:
        return float("inf") if net_profit > 0 else 0.0
    return round(net_profit / max_dd_abs, 4)


def _mar(return_pct: float, max_dd_pct: float) -> float:
    if max_dd_pct <= 0:
        return float("inf") if return_pct > 0 else 0.0
    return round(return_pct / max_dd_pct, 4)


def is_trend_trade(trade: ClosedTrade) -> bool:
    s = (trade.strategy or "").lower()
    meta = trade.entry_features or {}
    regime = str(meta.get("regime", meta.get("_regime", ""))).upper()
    return regime == "TREND" or "trend" in s or "v41" in s or "v40" in s


def is_range_trade(trade: ClosedTrade) -> bool:
    s = (trade.strategy or "").lower()
    meta = trade.entry_features or {}
    regime = str(meta.get("regime", meta.get("_regime", ""))).upper()
    return regime == "RANGE" or regime == "RANGING" or "phase9" in s or "range" in s or "ml_kernel" in s


def compute_extended_metrics(result: BacktestResult, timeframe: str) -> dict[str, Any]:
    base = compute_metrics(result, timeframe=timeframe)
    _, max_dd_abs = _max_drawdown(result.equity_curve)
    net = float(base["net_profit"])
    ret_pct = float(base["return_pct"])
    max_dd_pct = float(base["max_drawdown_pct"])
    sharpe = float(base["sharpe_ratio"])
    sortino = round(_sortino(result.equity_curve, timeframe), 4)
    recovery = _recovery_factor(net, max_dd_abs)
    mar = _mar(ret_pct, max_dd_pct)

    trades = result.trades
    buys = sum(1 for t in trades if t.is_buy)
    sells = len(trades) - buys
    trend_trades = sum(1 for t in trades if is_trend_trade(t))
    range_trades = sum(1 for t in trades if is_range_trade(t))

    pf = base["profit_factor"]
    pf_val = float(pf) if pf != "inf" else 999.0

    return {
        **base,
        "profit_factor": pf,
        "average_r": _average_r(trades),
        "recovery_factor": recovery if recovery != float("inf") else "inf",
        "sortino_ratio": sortino,
        "mar_ratio": mar if mar != float("inf") else "inf",
        "buy_trades": buys,
        "sell_trades": sells,
        "trend_trades": trend_trades,
        "range_trades": range_trades,
        "bars": len(result.equity_curve),
        "certification": {
            "pf_target_met": pf_val >= 1.30,
            "positive_expectancy": float(base["expectancy"]) > 0,
            "max_dd_within_limit": max_dd_pct <= 25.0,
            "buy_active": buys > 0,
            "sell_active": sells > 0,
        },
    }


def trades_to_mc_records(trades: list[ClosedTrade]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in trades:
        regime = "TREND" if is_trend_trade(t) else ("RANGE" if is_range_trade(t) else "UNKNOWN")
        adx = float((t.entry_features or {}).get("adx", 25.0))
        out.append({
            "timestamp": str(t.entry_time),
            "allowed": True,
            "r_multiple": t.r_multiple,
            "is_buy": t.is_buy,
            "regime": regime,
            "adx": adx,
            "timeframe": (t.entry_features or {}).get("timeframe", ""),
            "strategy": t.strategy,
        })
    return out
