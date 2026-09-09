"""محاسبه‌ی متریک‌های بک‌تست — profit factor واقعی، drawdown، Sharpe، ..."""

from __future__ import annotations

import math
from typing import Any

from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.cost_model import CostCompleteness, cost_source_summary

_BARS_PER_YEAR = {
    "M1": 252 * 24 * 60,
    "M5": 252 * 24 * 12,
    "M15": 252 * 24 * 4,
    "M30": 252 * 24 * 2,
    "H1": 252 * 24,
    "H4": 252 * 6,
    "D1": 252,
}


def compute_metrics(
    result: BacktestResult,
    timeframe: str = "M5",
    *,
    cost_completeness: str | CostCompleteness | None = None,
) -> dict[str, Any]:
    trades = result.trades
    n = len(trades)
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_profit = sum(pnls)

    win_rate = (len(wins) / n * 100) if n else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_win = (gross_profit / len(wins)) if wins else 0.0
    avg_loss = (-gross_loss / len(losses)) if losses else 0.0
    expectancy = (net_profit / n) if n else 0.0

    max_dd_pct, max_dd_abs = _max_drawdown(result.equity_curve)
    sharpe = _sharpe(result.equity_curve, timeframe)

    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1

    completeness = cost_completeness or getattr(result, "cost_completeness", CostCompleteness.UNKNOWN)
    if isinstance(completeness, CostCompleteness):
        completeness = completeness.value

    return {
        "total_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_profit": round(net_profit, 2),
        "return_pct": round(net_profit / result.initial_balance * 100, 2) if result.initial_balance else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 3),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_abs": round(max_dd_abs, 2),
        "sharpe_ratio": round(sharpe, 3),
        "final_balance": round(result.final_balance, 2),
        "exit_reasons": reasons,
        "cost_completeness": completeness,
        "cost_adjusted_metrics": completeness == CostCompleteness.COMPLETE.value,
        "cost_trace_count": len(getattr(result, "cost_traces", []) or []),
        "cost_source_summary": cost_source_summary(getattr(result, "cost_traces", []) or []),
        "pnl_basis": "modeled_costs_partial" if completeness != CostCompleteness.COMPLETE.value else "modeled_costs_complete",
        "dataset_provenance_count": len(getattr(result, "dataset_provenance", []) or []),
    }


def _max_drawdown(equity_curve: list[dict]) -> tuple[float, float]:
    peak = -float("inf")
    max_dd_pct = 0.0
    max_dd_abs = 0.0
    for point in equity_curve:
        eq = point.get("equity", 0.0)
        peak = max(peak, eq)
        if peak > 0:
            dd_abs = peak - eq
            dd_pct = dd_abs / peak * 100
            max_dd_abs = max(max_dd_abs, dd_abs)
            max_dd_pct = max(max_dd_pct, dd_pct)
    return max_dd_pct, max_dd_abs


def _sharpe(equity_curve: list[dict], timeframe: str) -> float:
    eqs = [p.get("equity", 0.0) for p in equity_curve]
    if len(eqs) < 3:
        return 0.0
    returns = []
    for i in range(1, len(eqs)):
        prev = eqs[i - 1]
        if prev != 0:
            returns.append((eqs[i] - prev) / prev)
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    ann = math.sqrt(_BARS_PER_YEAR.get(timeframe.upper(), 252 * 24 * 12))
    return mean / std * ann


def format_report(result: BacktestResult, metrics: dict[str, Any], timeframe: str) -> str:
    lines = [
        "=" * 56,
        " BACKTEST RESULT",
        "=" * 56,
        f" Symbols          : {result.config.symbols}",
        f" Timeframe        : {timeframe}",
        f" Initial balance  : {result.initial_balance:.2f}",
        f" Final balance    : {metrics['final_balance']:.2f}",
        f" Net profit       : {metrics['net_profit']:.2f}  ({metrics['return_pct']}%)",
        "-" * 56,
        f" Total trades     : {metrics['total_trades']}",
        f" Win rate         : {metrics['win_rate_pct']}%  ({metrics['wins']}W / {metrics['losses']}L)",
        f" Profit factor    : {metrics['profit_factor']}",
        f" Avg win / loss   : {metrics['avg_win']} / {metrics['avg_loss']}",
        f" Expectancy/trade : {metrics['expectancy']}",
        f" Max drawdown     : {metrics['max_drawdown_pct']}%  ({metrics['max_drawdown_abs']})",
        f" Sharpe (annual.) : {metrics['sharpe_ratio']}",
        f" Cost completeness: {metrics.get('cost_completeness', 'UNKNOWN')}",
        f" Cost traces       : {metrics.get('cost_trace_count', 0)}",
        f" Cost sources      : {metrics.get('cost_source_summary', {})}",
        f" PnL basis         : {metrics.get('pnl_basis', 'unknown')}",
        f" Cost-adjusted PF : {'yes' if metrics.get('cost_adjusted_metrics') else 'no — partial/unknown costs'}",
        f" Exit reasons     : {metrics['exit_reasons']}",
        "=" * 56,
    ]
    return "\n".join(lines)
