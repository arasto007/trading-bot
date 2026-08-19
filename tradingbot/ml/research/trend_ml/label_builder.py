"""Phase 13.4 — supervised labels for trend ML (causal, no shuffle)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS

from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal

MAX_HOLD_BARS = 72


def _simulate_outcome(
    work: pd.DataFrame,
    i: int,
    *,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> int | None:
    """
    TP before SL => 1, SL before TP => 0.
    Timeout bars are excluded (None) to keep labels unambiguous.
    """
    n = len(work)
    exit_bar = min(i + MAX_HOLD_BARS, n - 1)
    for j in range(i + 1, exit_bar + 1):
        bar = work.iloc[j]
        hi = float(bar["high"])
        lo = float(bar["low"])
        if direction == "BUY":
            if lo <= sl:
                return 0
            if hi >= tp:
                return 1
        else:
            if hi >= sl:
                return 0
            if lo <= tp:
                return 1
    return None


def build_supervised_labels(
    frame: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
) -> pd.DataFrame:
    """
    Chronological scan of Phase 13.3 signal bars.
    Labels use forward bars only at labeling time; WF splits prevent train/test leakage.
    """
    work = frame.copy().reset_index(drop=True)
    regimes = attach_regime_labels(work)
    rows: list[dict[str, Any]] = []

    for i in range(len(work) - 1):
        row = work.iloc[i]
        regime = str(regimes.iloc[i])
        direction = evaluate_trend_rules(row, regime=regime)
        if direction == "HOLD":
            continue

        signal = build_trend_signal(row, symbol=symbol, direction=direction)
        label = _simulate_outcome(
            work,
            i,
            direction=direction,
            entry=float(signal["entry"]),
            sl=float(signal["stop_loss"]),
            tp=float(signal["take_profit"]),
        )
        if label is None:
            continue

        rows.append(
            {
                "timestamp": row["timestamp"],
                "symbol": symbol,
                "direction": direction,
                "regime": regime,
                "successful_trade": int(label),
                "entry": signal["entry"],
                "stop_loss": signal["stop_loss"],
                "take_profit": signal["take_profit"],
                **{k: float(row[k]) for k in TREND_ML_FEATURE_COLUMNS if k in row.index},
            }
        )

    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
