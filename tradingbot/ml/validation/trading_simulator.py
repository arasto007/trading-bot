"""Offline trading simulator — TP=2R, SL=1R, no MT5."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.training import load_model
from tradingbot.ml.validation._utils import write_json_report

TP_R = 2.0
SL_R = 1.0


@dataclass
class TradingSimulation:
    model: str
    symbol: str
    timeframe: str
    split: str
    threshold: float
    total_trades: int
    winrate: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    max_consecutive_losses: int
    equity_curve: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _max_consecutive_losses(returns: np.ndarray) -> int:
    max_streak = 0
    current = 0
    for r in returns:
        if r < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    return round(float(dd.max()), 4)


def simulate_trades(
    y_true: np.ndarray,
    proba_pos: np.ndarray,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Take trades when proba >= threshold.

    Realized R: label=1 → +2R, label=0 → -1R (chronological order preserved).
    """
    take = proba_pos >= threshold
    labels = y_true[take]
    returns = np.where(labels == 1, TP_R, -SL_R)
    return returns, take


def run_trading_simulation(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    split: str = "test",
    threshold: float = 0.5,
    save: bool = False,
) -> TradingSimulation:
    splits = load_dataset_splits(symbol, timeframe, base_dir)
    split_map = {
        "train": (splits.train, splits.X_train, splits.y_train),
        "validation": (splits.validation, splits.X_val, splits.y_val),
        "test": (splits.test, splits.X_test, splits.y_test),
    }
    raw_df, X, y = split_map[split]
    if X.empty:
        raise ValueError(f"Split '{split}' is empty")

    model = load_model(model_name, base_dir)
    proba = model.predict_proba(X)
    y_true = np.asarray(y).astype(int)

    returns, take = simulate_trades(y_true, proba[:, 1], threshold)
    n_trades = int(len(returns))

    if n_trades == 0:
        sim = TradingSimulation(
            model=model_name.lower(),
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            split=split,
            threshold=threshold,
            total_trades=0,
            winrate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            max_drawdown=0.0,
            max_consecutive_losses=0,
            equity_curve=[0.0],
        )
    else:
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        gross_profit = float(wins.sum()) if len(wins) else 0.0
        gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
        pf = gross_profit / gross_loss if gross_loss > 0 else float(gross_profit)
        equity = np.cumsum(returns)
        sim = TradingSimulation(
            model=model_name.lower(),
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            split=split,
            threshold=threshold,
            total_trades=n_trades,
            winrate=round(float((returns > 0).mean()), 4),
            profit_factor=round(float(pf), 4),
            expectancy=round(float(returns.mean()), 4),
            max_drawdown=_max_drawdown(equity),
            max_consecutive_losses=_max_consecutive_losses(returns),
            equity_curve=[round(float(v), 4) for v in np.concatenate([[0.0], equity])],
        )

    if save:
        write_json_report(
            reports_dir(base_dir) / f"{symbol.upper()}_{timeframe.upper()}_{model_name.lower()}_simulation.json",
            sim.to_dict(),
        )

    return sim
