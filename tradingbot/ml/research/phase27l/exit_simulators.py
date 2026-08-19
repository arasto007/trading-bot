"""Phase 27L — simulated exit strategies (research-only, no production changes)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.paper_trading.paper_broker import PaperBroker
from tradingbot.ml.research.phase27l.exit_trace import MAX_HOLD_BARS, _entry_idx, _risk_unit

TRAIL_ATR_MULT = 1.0
SWING_LOOKBACK = 5
ATR_REVERSAL_MULT = 1.5

EXIT_STRATEGIES = (
    "current_tp_sl",
    "breakeven_0.5r",
    "breakeven_1r",
    "trailing_atr",
    "trailing_swing",
    "partial_close_50",
    "time_exit",
    "atr_exit",
    "structure_exit",
    "dynamic_tp_1.5r",
)


def _pnl(
    entry: float,
    exit_price: float,
    *,
    direction: str,
    lot: float,
    symbol: str,
) -> float:
    mult = 1 if direction == "BUY" else -1
    return round((exit_price - entry) * mult * contract_size(symbol) * lot, 4)


def _finalize(
    *,
    entry: float,
    exit_price: float,
    exit_reason: str,
    duration_bars: int,
    direction: str,
    lot: float,
    symbol: str,
    risk: float,
    exit_ts: str,
) -> dict[str, Any]:
    mult = 1 if direction == "BUY" else -1
    pnl = _pnl(entry, exit_price, direction=direction, lot=lot, symbol=symbol)
    pnl_r = round(((exit_price - entry) * mult) / risk, 4) if risk > 0 else 0.0
    return {
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 6),
        "exit_timestamp": exit_ts,
        "pnl": pnl,
        "pnl_r": pnl_r,
        "duration_bars": duration_bars,
    }


def simulate_exit(
    trade: dict[str, Any],
    frame: pd.DataFrame,
    strategy: str,
) -> dict[str, Any]:
    if strategy == "current_tp_sl":
        return {
            "strategy": strategy,
            "exit_reason": trade.get("exit_reason"),
            "exit_price": float(trade["exit_price"]),
            "exit_timestamp": trade.get("exit_timestamp"),
            "pnl": float(trade["pnl"]),
            "pnl_r": float(trade.get("pnl_r") or 0.0),
            "duration_bars": int(trade.get("duration_bars") or 0),
        }

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
    risk = _risk_unit(entry, sl_f)
    if risk <= 0 or sl_f is None:
        return simulate_exit(trade, frame, "current_tp_sl") | {"strategy": strategy}

    if strategy == "dynamic_tp_1.5r":
        if is_buy:
            tp_f = entry + 1.5 * risk
        else:
            tp_f = entry - 1.5 * risk

    end = min(start + MAX_HOLD_BARS, len(frame) - 1)
    broker = PaperBroker()

    effective_sl = sl_f
    be_armed_at: float | None = None
    if strategy == "breakeven_0.5r":
        be_armed_at = 0.5
    elif strategy == "breakeven_1r":
        be_armed_at = 1.0

    peak_price = entry
    trail_sl = sl_f
    partial_done = False
    partial_pnl = 0.0
    remaining_lot = lot
    mfe_r = 0.0

    exit_reason = "timeout"
    exit_price = float(frame.iloc[min(start + 1, len(frame) - 1)]["close"])
    exit_ts = pd.to_datetime(frame.index[min(start + 1, len(frame) - 1)], utc=True).isoformat()
    duration = 0

    for j in range(start + 1, end + 1):
        bar = frame.iloc[j]
        duration += 1
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        atr = float(bar.get("atr") or risk)

        if is_buy:
            mfe_r = max(mfe_r, (high - entry) / risk)
            peak_price = max(peak_price, high)
        else:
            mfe_r = max(mfe_r, (entry - low) / risk)
            peak_price = min(peak_price, low)

        if be_armed_at is not None and mfe_r >= be_armed_at:
            effective_sl = entry

        if strategy == "trailing_atr":
            if is_buy:
                trail_sl = max(trail_sl, peak_price - TRAIL_ATR_MULT * atr)
                effective_sl = trail_sl
            else:
                trail_sl = min(trail_sl, peak_price + TRAIL_ATR_MULT * atr)
                effective_sl = trail_sl

        if strategy == "trailing_swing":
            lb = max(start, j - SWING_LOOKBACK)
            sub = frame.iloc[lb:j]
            if is_buy:
                swing = float(sub["low"].min())
                effective_sl = max(effective_sl, swing)
            else:
                swing = float(sub["high"].max())
                effective_sl = min(effective_sl, swing)

        if strategy == "partial_close_50" and not partial_done and mfe_r >= 1.0:
            partial_price = entry + mult * risk
            partial_pnl = _pnl(entry, partial_price, direction=direction, lot=lot * 0.5, symbol=sym)
            remaining_lot = lot * 0.5
            partial_done = True

        if strategy == "structure_exit":
            ema20 = float(bar.get("ema_20") or close)
            if is_buy and close < ema20 and mfe_r >= 0.25:
                exit_reason = "structure"
                exit_price = close
                exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
                break
            if not is_buy and close > ema20 and mfe_r >= 0.25:
                exit_reason = "structure"
                exit_price = close
                exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
                break

        if strategy == "atr_exit" and mfe_r >= 0.5:
            drawdown = (peak_price - low) if is_buy else (high - peak_price)
            if drawdown >= ATR_REVERSAL_MULT * atr:
                exit_reason = "atr_reversal"
                exit_price = close
                exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
                break

        if strategy == "time_exit" and j == end:
            exit_reason = "time"
            exit_price = close
            exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
            break

        if tp_f is not None and strategy not in ("time_exit",):
            hit = broker.resolve_bar(bar, direction=mult, stop_loss=effective_sl, take_profit=tp_f)
            if hit:
                reason, price = hit
                exit_reason = reason.lower()
                exit_price = float(price)
                exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
                break
        elif strategy not in ("time_exit",):
            hit = broker.resolve_bar(bar, direction=mult, stop_loss=effective_sl, take_profit=entry + mult * 1e9)
            if hit and hit[0].upper() == "SL":
                exit_reason = "sl"
                exit_price = float(hit[1])
                exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
                break
    else:
        if strategy == "time_exit" or exit_reason == "timeout":
            exit_reason = "timeout"
            exit_price = float(frame.iloc[end]["close"])
            exit_ts = pd.to_datetime(frame.index[end], utc=True).isoformat()
            duration = end - start

    main_pnl = _pnl(entry, exit_price, direction=direction, lot=remaining_lot, symbol=sym)
    total_pnl = round(main_pnl + partial_pnl, 4)
    total_r = round(total_pnl / (risk * contract_size(sym) * lot), 4) if risk > 0 else 0.0

    return {
        "strategy": strategy,
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 6),
        "exit_timestamp": exit_ts,
        "pnl": total_pnl,
        "pnl_r": total_r,
        "duration_bars": duration,
        "partial_close_applied": partial_done,
    }


def simulate_all_strategies(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "timestamp": trade.get("timestamp"),
        "direction": trade.get("direction"),
        "baseline_pnl": float(trade["pnl"]),
        "strategies": {s: simulate_exit(trade, frame, s) for s in EXIT_STRATEGIES},
    }
