"""Phase 13.8 — variant backtest and comparison."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase11_5._metrics import trade_metrics
from tradingbot.ml.research.phase13_8.config import MAX_HOLD_BARS
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels
from tradingbot.ml.research.trend_strategy.trend_signal import RISK_PCT, build_trend_signal


def run_variant_backtest(
    frame: pd.DataFrame,
    *,
    symbol: str,
    rule_fn: Callable[..., str],
    initial_equity: float = 10_000.0,
    ml_filter: Callable[[pd.Series, str], bool] | None = None,
) -> dict[str, Any]:
    work = frame.copy().reset_index(drop=True)
    regimes = attach_regime_labels(work)
    trades: list[dict[str, Any]] = []
    equity = initial_equity
    i = 0
    n = len(work)

    while i < n - 1:
        row = work.iloc[i]
        regime = str(regimes.iloc[i])
        direction = rule_fn(row, regime=regime)
        if direction == "HOLD":
            i += 1
            continue
        if ml_filter is not None and not ml_filter(row, direction):
            i += 1
            continue

        signal = build_trend_signal(row, symbol=symbol, direction=direction)
        entry = float(signal["entry"])
        sl = float(signal["stop_loss"])
        tp = float(signal["take_profit"])
        risk_amount = equity * RISK_PCT
        r_unit = abs(entry - sl)
        result, exit_price, r_mult, exit_bar = "TIMEOUT", entry, 0.0, min(i + MAX_HOLD_BARS, n - 1)

        for j in range(i + 1, exit_bar + 1):
            bar = work.iloc[j]
            hi, lo = float(bar["high"]), float(bar["low"])
            if direction == "BUY":
                if lo <= sl:
                    result, exit_price, r_mult, exit_bar = "SL", sl, -1.0, j
                    break
                if hi >= tp:
                    result, exit_price, r_mult, exit_bar = "TP", tp, 2.0, j
                    break
            else:
                if hi >= sl:
                    result, exit_price, r_mult, exit_bar = "SL", sl, -1.0, j
                    break
                if lo <= tp:
                    result, exit_price, r_mult, exit_bar = "TP", tp, 2.0, j
                    break
            exit_price = float(bar["close"])
        if result == "TIMEOUT":
            r_mult = (exit_price - entry) / r_unit if direction == "BUY" and r_unit > 0 else (
                (entry - exit_price) / r_unit if r_unit > 0 else 0.0
            )

        pnl = r_mult * risk_amount
        equity += pnl
        trades.append(
            {
                "type": "trade",
                "timestamp": str(row["timestamp"]),
                "regime": regime,
                "direction": direction,
                "result": result,
                "R_multiple": round(r_mult, 4),
                "pnl": round(pnl, 4),
            }
        )
        i = exit_bar + 1

    metrics = trade_metrics(trades, initial_equity=initial_equity)
    metrics["expectancy"] = metrics.pop("expectancy_r", metrics.get("expectancy_r", 0.0))
    return {"trades": trades, "metrics": metrics, "chronological": True, "shuffle": False}


def compare_variants(
    frame: pd.DataFrame,
    variants: dict[str, tuple[str, Callable[..., str]]],
    *,
    symbol: str = "XAUUSD",
) -> list[dict[str, Any]]:
    rows = []
    for key, (label, fn) in variants.items():
        bt = run_variant_backtest(frame, symbol=symbol, rule_fn=fn)
        m = bt["metrics"]
        rows.append(
            {
                "variant": key,
                "label": label,
                "trades": m.get("trades", 0),
                "profit_factor": m.get("profit_factor", 0.0),
                "expectancy": m.get("expectancy", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "max_drawdown": m.get("max_drawdown", 0.0),
            }
        )
    return sorted(rows, key=lambda r: r.get("profit_factor", 0.0), reverse=True)
