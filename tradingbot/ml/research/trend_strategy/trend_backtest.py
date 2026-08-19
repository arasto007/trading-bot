"""Phase 13.3 — chronological trend strategy backtest (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase11_5._metrics import trade_metrics
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules
from tradingbot.ml.research.trend_strategy.trend_signal import RISK_PCT, build_trend_signal


def attach_regime_labels(frame: pd.DataFrame) -> pd.Series:
    """Phase 13.2 rule baseline regimes on trend feature rows."""
    regime_cols = frame[
        ["adx", "atr_percentile", "ema50_slope", "volatility", "spread_pips", "trend_strength"]
    ].copy() if "volatility" in frame.columns else frame[
        ["adx", "atr_percentile", "ema50_slope"]
    ].copy()
    if "spread_pips" not in regime_cols.columns:
        regime_cols["spread_pips"] = 0.0
    if "volatility" not in regime_cols.columns:
        regime_cols["volatility"] = 0.0
    if "trend_strength" not in regime_cols.columns:
        regime_cols["trend_strength"] = regime_cols["adx"]
    return rule_classify(regime_cols)


def run_trend_backtest(
    frame: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    initial_equity: float = 10_000.0,
    max_hold_bars: int = 72,
) -> dict[str, Any]:
    """
    Chronological bar-by-bar simulation.
    Only TREND regime entries; SL-first on simultaneous hits.
    """
    work = frame.copy().reset_index(drop=True)
    regimes = attach_regime_labels(work)
    work["regime"] = regimes

    trades: list[dict[str, Any]] = []
    equity = initial_equity
    i = 0
    n = len(work)

    while i < n - 1:
        row = work.iloc[i]
        regime = str(row["regime"])
        direction = evaluate_trend_rules(row, regime=regime)
        if direction == "HOLD":
            i += 1
            continue

        signal = build_trend_signal(row, symbol=symbol, direction=direction)
        entry = float(signal["entry"])
        sl = float(signal["stop_loss"])
        tp = float(signal["take_profit"])
        risk_amount = equity * RISK_PCT
        r_unit = abs(entry - sl)

        result = "TIMEOUT"
        exit_price = entry
        r_mult = 0.0
        exit_bar = min(i + max_hold_bars, n - 1)

        for j in range(i + 1, exit_bar + 1):
            bar = work.iloc[j]
            hi = float(bar["high"])
            lo = float(bar["low"])
            if direction == "BUY":
                if lo <= sl:
                    result, exit_price, r_mult = "SL", sl, -1.0
                    exit_bar = j
                    break
                if hi >= tp:
                    result, exit_price, r_mult = "TP", tp, 2.0
                    exit_bar = j
                    break
            else:
                if hi >= sl:
                    result, exit_price, r_mult = "SL", sl, -1.0
                    exit_bar = j
                    break
                if lo <= tp:
                    result, exit_price, r_mult = "TP", tp, 2.0
                    exit_bar = j
                    break
            exit_price = float(bar["close"])

        if result == "TIMEOUT":
            if direction == "BUY":
                r_mult = (exit_price - entry) / r_unit if r_unit > 0 else 0.0
            else:
                r_mult = (entry - exit_price) / r_unit if r_unit > 0 else 0.0

        pnl = r_mult * risk_amount
        equity += pnl
        trades.append(
            {
                **signal,
                "exit": round(exit_price, 6),
                "result": result,
                "R_multiple": round(r_mult, 4),
                "pnl": round(pnl, 4),
                "duration_bars": exit_bar - i,
                "regime_at_entry": regime,
            }
        )
        i = exit_bar + 1

    metrics = trade_metrics(trades, initial_equity=initial_equity)
    monthly = _monthly_performance(trades)
    regime_perf = _regime_performance(trades)

    return {
        "trades": trades,
        "metrics": metrics,
        "monthly_performance": monthly,
        "regime_performance": regime_perf,
        "trend_only": all(t.get("regime_at_entry") == "TREND" for t in trades) if trades else True,
        "chronological": True,
        "shuffle": False,
    }


def _monthly_performance(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []
    rows: dict[str, list[float]] = {}
    for t in trades:
        month = pd.Timestamp(t["timestamp"]).strftime("%Y-%m")
        rows.setdefault(month, []).append(float(t.get("pnl", 0)))
    return [
        {"month": m, "trades": len(ps), "pnl": round(sum(ps), 4)}
        for m, ps in sorted(rows.items())
    ]


def _regime_performance(trades: list[dict[str, Any]]) -> dict[str, Any]:
    trend_trades = [t for t in trades if t.get("regime_at_entry") == "TREND"]
    return trade_metrics(trend_trades)
