"""Phase 27N — hybrid exit simulators (research-only, no production changes)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.paper_trading.paper_broker import PaperBroker
from tradingbot.ml.research.phase27l.exit_simulators import simulate_exit
from tradingbot.ml.research.phase27l.exit_trace import MAX_HOLD_BARS, _entry_idx, _risk_unit

TRAIL_ATR_MULT = 1.0
ATR_REVERSAL_MULT = 1.5

BASELINE_STRATEGIES = (
    "current_tp_sl",
    "time_exit",
    "partial_close_50",
    "structure_exit",
)

HYBRID_STRATEGIES = (
    "hybrid_a",
    "hybrid_b",
    "hybrid_c",
    "hybrid_d",
    "hybrid_e",
)

ALL_STRATEGIES = BASELINE_STRATEGIES + HYBRID_STRATEGIES


def _pnl(entry: float, exit_price: float, *, direction: str, lot: float, symbol: str) -> float:
    mult = 1 if direction == "BUY" else -1
    return round((exit_price - entry) * mult * contract_size(symbol) * lot, 4)


def simulate_hybrid(trade: dict[str, Any], frame: pd.DataFrame, hybrid: str) -> dict[str, Any]:
    start = _entry_idx(frame, trade)
    entry = float(trade["entry_price"])
    sl = trade.get("sl")
    sl_f = float(sl) if sl is not None else None
    direction = str(trade["direction"])
    is_buy = direction == "BUY"
    mult = 1 if is_buy else -1
    lot = float(trade.get("lot") or 0.01)
    sym = str(trade.get("symbol") or "XAUUSD")
    risk = _risk_unit(entry, sl_f)
    if risk <= 0 or sl_f is None:
        return simulate_exit(trade, frame, "current_tp_sl") | {"strategy": hybrid}

    end = min(start + MAX_HOLD_BARS, len(frame) - 1)
    broker = PaperBroker()

    effective_sl = sl_f
    peak_price = entry
    trail_sl = sl_f
    partial_done = False
    partial_pnl = 0.0
    remaining_lot = lot
    be_armed = False
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

        if hybrid == "hybrid_c" and not be_armed and mfe_r >= 1.0:
            effective_sl = entry
            be_armed = True

        if hybrid in ("hybrid_a", "hybrid_b", "hybrid_d", "hybrid_e") and not partial_done and mfe_r >= 1.0:
            partial_price = entry + mult * risk
            partial_pnl = _pnl(entry, partial_price, direction=direction, lot=lot * 0.5, symbol=sym)
            remaining_lot = lot * 0.5
            partial_done = True
            if hybrid == "hybrid_d":
                effective_sl = entry + mult * 0.25 * risk

        if hybrid == "hybrid_e" and partial_done and mfe_r >= 1.5:
            if is_buy:
                trail_sl = max(trail_sl, peak_price - TRAIL_ATR_MULT * atr)
                effective_sl = max(effective_sl, trail_sl)
            else:
                trail_sl = min(trail_sl, peak_price + TRAIL_ATR_MULT * atr)
                effective_sl = min(effective_sl, trail_sl)

        use_structure = hybrid in ("hybrid_a", "hybrid_c", "hybrid_d") and (
            partial_done or hybrid == "hybrid_c"
        )
        if use_structure or (hybrid == "hybrid_c" and be_armed):
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

        if hybrid == "hybrid_b" and partial_done and j == end:
            exit_reason = "time"
            exit_price = close
            exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
            break

        if hybrid == "hybrid_b" and not partial_done and j == end:
            exit_reason = "time"
            exit_price = close
            exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
            break

        hit = broker.resolve_bar(
            bar,
            direction=mult,
            stop_loss=effective_sl,
            take_profit=entry + mult * 1e9,
        )
        if hit and hit[0].upper() == "SL":
            exit_reason = "sl"
            exit_price = float(hit[1])
            exit_ts = pd.to_datetime(frame.index[j], utc=True).isoformat()
            break
    else:
        exit_reason = "timeout"
        exit_price = float(frame.iloc[end]["close"])
        exit_ts = pd.to_datetime(frame.index[end], utc=True).isoformat()
        duration = end - start

    main_pnl = _pnl(entry, exit_price, direction=direction, lot=remaining_lot, symbol=sym)
    total_pnl = round(main_pnl + partial_pnl, 4)
    total_r = round(total_pnl / (risk * contract_size(sym) * lot), 4) if risk > 0 else 0.0

    return {
        "strategy": hybrid,
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 6),
        "exit_timestamp": exit_ts,
        "pnl": total_pnl,
        "pnl_r": total_r,
        "duration_bars": duration,
        "partial_close_applied": partial_done,
    }


def simulate_strategy(trade: dict[str, Any], frame: pd.DataFrame, strategy: str) -> dict[str, Any]:
    if strategy in HYBRID_STRATEGIES:
        return simulate_hybrid(trade, frame, strategy)
    return simulate_exit(trade, frame, strategy)


def simulate_all_strategies(trade: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "timestamp": trade.get("timestamp"),
        "direction": trade.get("direction"),
        "baseline_pnl": float(trade["pnl"]),
        "strategies": {s: simulate_strategy(trade, frame, s) for s in ALL_STRATEGIES},
    }
