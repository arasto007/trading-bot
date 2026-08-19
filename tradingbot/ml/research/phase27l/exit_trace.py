"""Phase 27L — bar-by-bar trade trace after entry (research-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain import indicators
from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.paper_trading.paper_broker import PaperBroker

MAX_HOLD_BARS = 72
R_MILESTONES = (0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 2.5)


def _risk_unit(entry: float, sl: float | None) -> float:
    if sl is None or entry <= 0:
        return 0.0
    return abs(entry - float(sl))


def _entry_idx(frame: pd.DataFrame, trade: dict[str, Any]) -> int:
    if trade.get("bar_index") is not None:
        return min(max(int(trade["bar_index"]), 0), len(frame) - 1)
    ts = pd.to_datetime(trade["timestamp"], utc=True)
    return min(int(frame.index.searchsorted(ts)), len(frame) - 1)


def prepare_indicator_frame(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
    if "atr" not in frame.columns:
        frame = indicators.compute_indicators(frame, symbol="XAUUSD", timeframe="M5")
    return frame


def trace_trade_bars(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    """Reconstruct every bar from entry until actual exit (or max hold)."""
    start = _entry_idx(frame, trade)
    entry = float(trade["entry_price"])
    sl = trade.get("sl")
    sl_f = float(sl) if sl is not None else None
    tp = trade.get("tp")
    tp_f = float(tp) if tp is not None else None
    direction = str(trade["direction"])
    is_buy = direction == "BUY"
    mult = 1 if is_buy else -1
    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")
    cs = contract_size(sym)
    risk = _risk_unit(entry, sl_f)

    actual_duration = int(trade.get("duration_bars") or MAX_HOLD_BARS)
    end = min(start + max(actual_duration, 1), start + MAX_HOLD_BARS, len(frame) - 1)

    broker = PaperBroker()
    bars: list[dict[str, Any]] = []
    mfe_r = 0.0
    mae_r = 0.0
    exit_bar = end

    for j in range(start + 1, end + 1):
        row = frame.iloc[j]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        duration = j - start

        if risk > 0:
            if is_buy:
                mae_r = max(mae_r, max(0.0, (entry - low) / risk))
                mfe_r = max(mfe_r, max(0.0, (high - entry) / risk))
            else:
                mae_r = max(mae_r, max(0.0, (high - entry) / risk))
                mfe_r = max(mfe_r, max(0.0, (entry - low) / risk))

        current_r = ((close - entry) * mult) / risk if risk > 0 else 0.0
        pnl = round((close - entry) * mult * cs * lot, 4)

        bars.append(
            {
                "bar_index": j,
                "timestamp": pd.to_datetime(frame.index[j], utc=True).isoformat(),
                "duration_bars": duration,
                "open": float(row["open"]),
                "high": high,
                "low": low,
                "close": close,
                "current_r": round(current_r, 4),
                "current_pnl": pnl,
                "atr": round(float(row.get("atr") or 0.0), 4),
                "adx": round(float(row.get("adx") or 0.0), 4),
                "rsi": round(float(row.get("rsi") or 0.0), 4),
                "running_mfe_r": round(mfe_r, 4),
                "running_mae_r": round(mae_r, 4),
            }
        )

        if sl_f is not None and tp_f is not None:
            hit = broker.resolve_bar(row, direction=mult, stop_loss=sl_f, take_profit=tp_f)
            if hit:
                exit_bar = j
                break
    else:
        exit_bar = end

    return {
        "timestamp": trade.get("timestamp"),
        "direction": direction,
        "entry_price": entry,
        "exit_reason": trade.get("exit_reason"),
        "actual_duration_bars": actual_duration,
        "simulated_exit_bar": exit_bar,
        "max_mfe_r": round(mfe_r, 4),
        "bars": bars,
    }


def build_profit_timeline(trace: dict[str, Any], risk: float, is_buy: bool) -> dict[str, Any]:
    """Bars until each R milestone is first reached."""
    entry = float(trace["entry_price"])
    mult = 1 if is_buy else -1
    milestones: dict[str, int | None] = {f"R_{str(m).replace('.', '_')}": None for m in R_MILESTONES}
    max_mfe_bar: int | None = None
    peak_mfe = 0.0

    for bar in trace["bars"]:
        dur = bar["duration_bars"]
        mfe = float(bar["running_mfe_r"])
        if mfe > peak_mfe:
            peak_mfe = mfe
            max_mfe_bar = dur
        for m in R_MILESTONES:
            key = f"R_{str(m).replace('.', '_')}"
            if milestones[key] is None and mfe >= m:
                milestones[key] = dur

    profitable_bars = sum(1 for b in trace["bars"] if b["current_r"] > 0)
    return {
        "timestamp": trace.get("timestamp"),
        "milestones_bars": milestones,
        "max_mfe_r": trace.get("max_mfe_r"),
        "max_mfe_bar": max_mfe_bar,
        "bars_profitable": profitable_bars,
        "bars_total": len(trace["bars"]),
        "pct_bars_profitable": round(100.0 * profitable_bars / max(len(trace["bars"]), 1), 2),
    }


def build_reversal_stats(trace: dict[str, Any]) -> dict[str, Any]:
    """After reaching R level, bars until back to 0R or -1R."""
    bars = trace["bars"]
    if not bars:
        return {}
    out: dict[str, Any] = {}
    for m in R_MILESTONES:
        key = f"R_{str(m).replace('.', '_')}"
        hit_idx = None
        for i, b in enumerate(bars):
            if float(b["running_mfe_r"]) >= m:
                hit_idx = i
                break
        if hit_idx is None:
            out[key] = {"reached": False}
            continue
        bars_to_zero = None
        bars_to_neg1 = None
        for j in range(hit_idx, len(bars)):
            r = float(bars[j]["current_r"])
            if bars_to_zero is None and r <= 0:
                bars_to_zero = bars[j]["duration_bars"] - bars[hit_idx]["duration_bars"]
            if bars_to_neg1 is None and r <= -1.0:
                bars_to_neg1 = bars[j]["duration_bars"] - bars[hit_idx]["duration_bars"]
        out[key] = {
            "reached": True,
            "bars_to_zero_r": bars_to_zero,
            "bars_to_neg1_r": bars_to_neg1,
            "reversed": bars_to_zero is not None,
        }
    return out
