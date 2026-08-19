"""Production exit policies — CURRENT TP/SL and Hybrid B."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.paper_trading.paper_broker import PaperBroker
from tradingbot.services.exit_mode import ExitMode

DEFAULT_MAX_HOLD_BARS = 72
PARTIAL_FRACTION = 0.50
PARTIAL_TRIGGER_R = 1.0


def _risk_unit(entry: float, sl: float | None) -> float:
    if sl is None or entry <= 0:
        return 0.0
    return abs(entry - float(sl))


def _rr(entry: float, sl: float | None, tp: float | None, is_buy: bool) -> float | None:
    risk = _risk_unit(entry, sl)
    if risk <= 0 or tp is None:
        return None
    reward = (tp - entry) if is_buy else (entry - tp)
    return round(reward / risk, 4)


def _pnl(entry: float, exit_price: float, *, is_buy: bool, lot: float, symbol: str) -> float:
    direction = 1 if is_buy else -1
    return round((exit_price - entry) * direction * contract_size(symbol) * lot, 4)


def _finalize(
    *,
    entry_price: float,
    entry_ts: str,
    exit_price: float,
    exit_ts: pd.Timestamp,
    exit_reason: str,
    is_buy: bool,
    lot: float,
    symbol: str,
    sl: float | None,
    tp: float | None,
    bars_held: int,
    mae: float,
    mfe: float,
    spread: float,
    partial_pnl: float = 0.0,
    partial_close_applied: bool = False,
    remaining_lot: float | None = None,
) -> dict[str, Any]:
    entry_time = pd.to_datetime(entry_ts, utc=True)
    exit_norm = pd.Timestamp(exit_ts)
    if exit_norm.tzinfo is None:
        exit_norm = exit_norm.tz_localize("UTC")
    else:
        exit_norm = exit_norm.tz_convert("UTC")
    duration_sec = int(max(0, (exit_norm - entry_time).total_seconds()))
    risk = _risk_unit(entry_price, sl)
    rem_lot = remaining_lot if remaining_lot is not None else lot
    main_pnl = _pnl(entry_price, exit_price, is_buy=is_buy, lot=rem_lot, symbol=symbol)
    total_pnl = round(main_pnl + partial_pnl, 4)
    direction = 1 if is_buy else -1
    pnl_r = 0.0
    if risk > 0:
        pnl_r = round(total_pnl / (risk * contract_size(symbol) * lot), 4)
    return {
        "exit_reason": exit_reason.lower(),
        "exit_price": round(exit_price, 6),
        "exit_timestamp": exit_norm.isoformat(),
        "pnl": total_pnl,
        "pnl_r": round(pnl_r, 4),
        "duration_bars": bars_held,
        "duration_sec": duration_sec,
        "mae": round(mae, 6),
        "mfe": round(mfe, 6),
        "spread": spread,
        "rr": _rr(entry_price, sl, tp, is_buy),
        "partial_close_applied": partial_close_applied,
        "partial_pnl": round(partial_pnl, 4),
        "remaining_lot": round(rem_lot, 4),
    }


def resolve_current_tp_sl(
    *,
    candles: pd.DataFrame,
    entry_ts: str,
    entry_price: float,
    sl: float | None,
    tp: float | None,
    is_buy: bool,
    lot: float,
    symbol: str,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
    spread: float = 0.30,
) -> dict[str, Any]:
    """Original production TP/SL + timeout exit."""
    if candles is None or candles.empty or entry_price <= 0:
        return _finalize(
            entry_price=entry_price,
            entry_ts=entry_ts,
            exit_price=entry_price,
            exit_ts=pd.to_datetime(entry_ts, utc=True),
            exit_reason="no_data",
            is_buy=is_buy,
            lot=lot,
            symbol=symbol,
            sl=sl,
            tp=tp,
            bars_held=0,
            mae=0.0,
            mfe=0.0,
            spread=spread,
        )

    idx = pd.DatetimeIndex(pd.to_datetime(candles.index, utc=True))
    candles = candles.copy()
    candles.index = idx
    entry_time = pd.to_datetime(entry_ts, utc=True)
    start = int(candles.index.searchsorted(entry_time))
    if start >= len(candles):
        start = len(candles) - 1

    broker = PaperBroker()
    direction = 1 if is_buy else -1
    risk = _risk_unit(entry_price, sl)
    mae = 0.0
    mfe = 0.0
    bars_held = 0
    exit_reason = "timeout"
    exit_price = float(candles.iloc[min(start + 1, len(candles) - 1)]["close"])
    exit_ts = candles.index[min(start + 1, len(candles) - 1)]

    end = min(start + max_hold_bars, len(candles) - 1)
    for j in range(start + 1, end + 1):
        bar = candles.iloc[j]
        bars_held += 1
        high = float(bar["high"])
        low = float(bar["low"])
        if is_buy:
            if risk > 0:
                mae = max(mae, max(0.0, (entry_price - low) / risk))
                mfe = max(mfe, max(0.0, (high - entry_price) / risk))
        else:
            if risk > 0:
                mae = max(mae, max(0.0, (high - entry_price) / risk))
                mfe = max(mfe, max(0.0, (entry_price - low) / risk))

        if sl is not None and tp is not None:
            hit = broker.resolve_bar(bar, direction=direction, stop_loss=sl, take_profit=tp)
            if hit:
                exit_reason, exit_price = hit
                exit_ts = candles.index[j]
                break
    else:
        exit_price = float(candles.iloc[end]["close"])
        exit_ts = candles.index[end]

    return _finalize(
        entry_price=entry_price,
        entry_ts=entry_ts,
        exit_price=float(exit_price),
        exit_ts=exit_ts,
        exit_reason=exit_reason,
        is_buy=is_buy,
        lot=lot,
        symbol=symbol,
        sl=sl,
        tp=tp,
        bars_held=bars_held,
        mae=mae,
        mfe=mfe,
        spread=spread,
    )


def resolve_hybrid_b(
    *,
    candles: pd.DataFrame,
    entry_ts: str,
    entry_price: float,
    sl: float | None,
    tp: float | None,
    is_buy: bool,
    lot: float,
    symbol: str,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
    spread: float = 0.30,
) -> dict[str, Any]:
    """
    Hybrid B: partial close 50% at +1R, remainder time-exits at max_hold_bars.
    Original SL maintained; no SL move after partial.
    """
    if candles is None or candles.empty or entry_price <= 0:
        return _finalize(
            entry_price=entry_price,
            entry_ts=entry_ts,
            exit_price=entry_price,
            exit_ts=pd.to_datetime(entry_ts, utc=True),
            exit_reason="no_data",
            is_buy=is_buy,
            lot=lot,
            symbol=symbol,
            sl=sl,
            tp=tp,
            bars_held=0,
            mae=0.0,
            mfe=0.0,
            spread=spread,
        )

    sl_f = float(sl) if sl is not None else None
    risk = _risk_unit(entry_price, sl_f)
    if risk <= 0 or sl_f is None:
        return resolve_current_tp_sl(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            is_buy=is_buy,
            lot=lot,
            symbol=symbol,
            max_hold_bars=max_hold_bars,
            spread=spread,
        )

    idx = pd.DatetimeIndex(pd.to_datetime(candles.index, utc=True))
    candles = candles.copy()
    candles.index = idx
    entry_time = pd.to_datetime(entry_ts, utc=True)
    start = int(candles.index.searchsorted(entry_time))
    if start >= len(candles):
        start = len(candles) - 1

    broker = PaperBroker()
    direction = 1 if is_buy else -1
    mult = direction
    effective_sl = sl_f
    partial_done = False
    partial_pnl = 0.0
    remaining_lot = lot
    mae = 0.0
    mfe = 0.0
    mfe_r = 0.0
    bars_held = 0
    exit_reason = "timeout"
    exit_price = float(candles.iloc[min(start + 1, len(candles) - 1)]["close"])
    exit_ts = candles.index[min(start + 1, len(candles) - 1)]

    end = min(start + max_hold_bars, len(candles) - 1)
    for j in range(start + 1, end + 1):
        bar = candles.iloc[j]
        bars_held += 1
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])

        if is_buy:
            mfe_r = max(mfe_r, (high - entry_price) / risk)
            mae = max(mae, max(0.0, (entry_price - low) / risk))
            mfe = max(mfe, max(0.0, (high - entry_price) / risk))
        else:
            mfe_r = max(mfe_r, (entry_price - low) / risk)
            mae = max(mae, max(0.0, (high - entry_price) / risk))
            mfe = max(mfe, max(0.0, (entry_price - low) / risk))

        if not partial_done and mfe_r >= PARTIAL_TRIGGER_R:
            partial_price = entry_price + mult * risk
            partial_pnl = _pnl(entry_price, partial_price, is_buy=is_buy, lot=lot * PARTIAL_FRACTION, symbol=symbol)
            remaining_lot = lot * (1.0 - PARTIAL_FRACTION)
            partial_done = True

        if j == end:
            exit_reason = "time"
            exit_price = close
            exit_ts = candles.index[j]
            break

        hit = broker.resolve_bar(
            bar,
            direction=direction,
            stop_loss=effective_sl,
            take_profit=entry_price + mult * 1e9,
        )
        if hit and hit[0].upper() == "SL":
            exit_reason = "sl"
            exit_price = float(hit[1])
            exit_ts = candles.index[j]
            break
    else:
        exit_price = float(candles.iloc[end]["close"])
        exit_ts = candles.index[end]

    if partial_done and exit_reason == "time":
        exit_reason = "hybrid_time"
    elif partial_done and exit_reason == "sl":
        exit_reason = "hybrid_sl"

    return _finalize(
        entry_price=entry_price,
        entry_ts=entry_ts,
        exit_price=float(exit_price),
        exit_ts=exit_ts,
        exit_reason=exit_reason,
        is_buy=is_buy,
        lot=lot,
        symbol=symbol,
        sl=sl,
        tp=tp,
        bars_held=bars_held,
        mae=mae,
        mfe=mfe,
        spread=spread,
        partial_pnl=partial_pnl,
        partial_close_applied=partial_done,
        remaining_lot=remaining_lot,
    )


def resolve_exit(
    *,
    exit_mode: ExitMode | str = ExitMode.CURRENT,
    candles: pd.DataFrame,
    entry_ts: str,
    entry_price: float,
    sl: float | None,
    tp: float | None,
    is_buy: bool,
    lot: float,
    symbol: str,
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
    spread: float = 0.30,
) -> dict[str, Any]:
    mode = exit_mode if isinstance(exit_mode, ExitMode) else ExitMode(str(exit_mode).upper())
    if mode == ExitMode.HYBRID_B:
        return resolve_hybrid_b(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            is_buy=is_buy,
            lot=lot,
            symbol=symbol,
            max_hold_bars=max_hold_bars,
            spread=spread,
        )
    return resolve_current_tp_sl(
        candles=candles,
        entry_ts=entry_ts,
        entry_price=entry_price,
        sl=sl,
        tp=tp,
        is_buy=is_buy,
        lot=lot,
        symbol=symbol,
        max_hold_bars=max_hold_bars,
        spread=spread,
    )
