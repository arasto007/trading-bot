"""Performance metrics for Phase 8.7 backtesting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from tradingbot.ml.backtest.state import BacktestState, SignalAction, SimulatedTrade


@dataclass
class BacktestMetrics:
    total_return: float = 0.0
    net_profit: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    max_drawdown: float = 0.0
    sharpe_proxy: float = 0.0
    num_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_time_in_trade_bars: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    signal_precision: float = 0.0
    signal_recall: float = 0.0
    confusion_matrix: dict[str, int] = field(default_factory=dict)
    prediction_distribution: dict[str, float] = field(default_factory=dict)
    model_quality: dict[str, float] = field(default_factory=dict)
    trade_quality: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _max_consecutive(mask: list[bool]) -> int:
    best = cur = 0
    for v in mask:
        if v:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _sharpe_proxy(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std <= 1e-12:
        return 0.0
    return float(np.mean(returns) / std * np.sqrt(len(returns)))


def compute_confusion_matrix(trades: list[SimulatedTrade]) -> dict[str, int]:
    """Signal taken vs label outcome (TP=1 win, SL=0 loss)."""
    matrix = {
        "true_positive": 0,
        "false_positive": 0,
        "true_negative": 0,
        "false_negative": 0,
    }
    for t in trades:
        predicted_win = t.signal == SignalAction.BUY
        actual_win = t.label == 1
        if predicted_win and actual_win:
            matrix["true_positive"] += 1
        elif predicted_win and not actual_win:
            matrix["false_positive"] += 1
        elif not predicted_win and not actual_win:
            matrix["true_negative"] += 1
        else:
            matrix["false_negative"] += 1
    return matrix


def compute_metrics(state: BacktestState, *, signals: list[dict[str, Any]] | None = None) -> BacktestMetrics:
    trades = state.closed_trades
    metrics = BacktestMetrics()
    metrics.num_trades = len(trades)
    metrics.net_profit = round(state.equity - state.initial_equity, 4)

    signal_rows = signals if signals is not None else state.signals
    if signal_rows:
        probs = [float(s.get("probability", 0.5)) for s in signal_rows]
        metrics.prediction_distribution = {
            "mean_probability": round(float(np.mean(probs)), 4),
            "min_probability": round(float(np.min(probs)), 4),
            "max_probability": round(float(np.max(probs)), 4),
            "buy_signals": float(sum(1 for s in signal_rows if s.get("signal") == SignalAction.BUY.value)),
            "sell_signals": float(sum(1 for s in signal_rows if s.get("signal") == SignalAction.SELL.value)),
            "hold_signals": float(sum(1 for s in signal_rows if s.get("signal") == SignalAction.HOLD.value)),
        }

    if not trades:
        metrics.confusion_matrix = compute_confusion_matrix(trades)
        return metrics

    pnls = np.array([t.pnl for t in trades], dtype=np.float64)
    pnl_r = np.array([t.pnl_r for t in trades], dtype=np.float64)
    wins = pnls > 0
    losses = pnls < 0

    metrics.total_return = round(
        (state.equity - state.initial_equity) / state.initial_equity,
        4,
    )
    metrics.win_rate = round(float(wins.mean()), 4)
    gross_profit = float(pnls[wins].sum()) if wins.any() else 0.0
    gross_loss = float(-pnls[losses].sum()) if losses.any() else 0.0
    metrics.profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else (
        round(gross_profit, 4) if gross_profit > 0 else 0.0
    )
    metrics.expectancy_r = round(float(pnl_r.mean()), 4)
    metrics.max_drawdown = round(
        max((p.drawdown for p in state.equity_curve), default=0.0),
        4,
    )
    metrics.sharpe_proxy = round(_sharpe_proxy(pnls / max(state.initial_equity, 1.0)), 4)

    win_pnls = pnls[wins]
    loss_pnls = pnls[losses]
    metrics.avg_win = round(float(win_pnls.mean()), 4) if len(win_pnls) else 0.0
    metrics.avg_loss = round(float(loss_pnls.mean()), 4) if len(loss_pnls) else 0.0
    metrics.avg_time_in_trade_bars = round(
        float(np.mean([t.bars_held for t in trades])),
        2,
    )
    metrics.max_consecutive_wins = _max_consecutive(wins.tolist())
    metrics.max_consecutive_losses = _max_consecutive(losses.tolist())

    matrix = compute_confusion_matrix(trades)
    metrics.confusion_matrix = matrix
    tp = matrix["true_positive"]
    fp = matrix["false_positive"]
    fn = matrix["false_negative"]
    metrics.signal_precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    metrics.signal_recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0

    buy_trades = [t for t in trades if t.signal == SignalAction.BUY]
    if buy_trades:
        pred_acc = sum(1 for t in buy_trades if t.predicted_class == t.label) / len(buy_trades)
    else:
        pred_acc = 0.0

    metrics.model_quality = {
        "signal_precision": metrics.signal_precision,
        "signal_recall": metrics.signal_recall,
        "prediction_accuracy": round(pred_acc, 4),
    }
    metrics.trade_quality = {
        "avg_win": metrics.avg_win,
        "avg_loss": metrics.avg_loss,
        "avg_time_in_trade_bars": metrics.avg_time_in_trade_bars,
        "max_consecutive_wins": float(metrics.max_consecutive_wins),
        "max_consecutive_losses": float(metrics.max_consecutive_losses),
    }
    return metrics
