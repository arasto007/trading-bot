"""Performance metrics from accounting ledger — single aggregation path."""

from __future__ import annotations

import statistics
from typing import Any

from tradingbot.accounting.ledger import AccountingLedger
from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _profit_factor


def compute_performance_metrics(ledger: AccountingLedger, *, timeframe: str = "M5") -> dict[str, Any]:
    trades = ledger.closed_trades
    if not trades:
        return {
            "initial_balance": ledger.initial_balance,
            "final_balance": ledger.balance,
            "net_profit": 0.0,
            "completed_trades": 0,
        }

    pnls = [float(t.pnl) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    initial = ledger.initial_balance
    ret_pct = net / initial * 100 if initial else 0.0
    dd_pct, dd_abs = _max_drawdown(ledger.equity_curve)

    trade_dicts = [t.to_dict() for t in trades]
    return {
        "initial_balance": initial,
        "final_balance": round(ledger.balance, 4),
        "net_profit": round(net, 4),
        "gross_profit": round(sum(wins), 4),
        "gross_loss": round(sum(losses), 4),
        "profit_factor": _profit_factor(trade_dicts),
        "expectancy": round(net / len(trades), 4),
        "recovery_factor": _recovery_factor(net, dd_abs),
        "sharpe_ratio": round(_sharpe(ledger.equity_curve, timeframe), 4),
        "sortino_ratio": round(_sortino(ledger.equity_curve, timeframe), 4),
        "calmar_ratio": round(ret_pct / dd_pct, 4) if dd_pct > 0 else 0.0,
        "max_drawdown_pct": round(dd_pct, 4),
        "max_drawdown_abs": round(dd_abs, 4),
        "completed_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "average_actual_risk_pct": round(
            statistics.mean([t.actual_risk_percent for t in trades]), 4
        ) if trades else 0.0,
    }
