"""Persistent position state for bar-by-bar Hybrid B replay (Phase 31E)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size
from tradingbot.ml.paper_trading.paper_broker import PaperBroker
from tradingbot.services.exit_mode import ExitMode
from tradingbot.services.exit_policy import (
    DEFAULT_MAX_HOLD_BARS,
    PARTIAL_FRACTION,
    PARTIAL_TRIGGER_R,
    _finalize,
    _pnl,
    _risk_unit,
    _rr,
)


@dataclass
class ReplayPositionState:
    """Survives across replay bars — never reinitialized per bar."""

    entry_timestamp: str
    entry_price: float
    entry_bar_index: int
    direction: str
    symbol: str
    sl: float | None
    tp: float | None
    original_lot: float
    remaining_volume: float
    partial_executed: bool = False
    partial_timestamp: str | None = None
    partial_price: float | None = None
    partial_pnl: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    mfe_r: float = 0.0
    bars_held: int = 0
    timeout_bar_index: int = 0
    sl_state: float | None = None
    closed: bool = False
    close_reason: str | None = None
    exit_price: float | None = None
    exit_timestamp: str | None = None
    spread: float = 0.30
    max_hold_bars: int = DEFAULT_MAX_HOLD_BARS
    last_processed_bar: int = -1
    exit_mode: str = ExitMode.HYBRID_B.value

    @classmethod
    def from_open(
        cls,
        *,
        entry_timestamp: str,
        entry_price: float,
        entry_bar_index: int,
        direction: str,
        symbol: str,
        sl: float | None,
        tp: float | None,
        lot: float,
        exit_mode: str | ExitMode,
        spread: float = 0.30,
        max_hold_bars: int = DEFAULT_MAX_HOLD_BARS,
    ) -> ReplayPositionState:
        mode = exit_mode.value if isinstance(exit_mode, ExitMode) else str(exit_mode).upper()
        sl_f = float(sl) if sl is not None else None
        return cls(
            entry_timestamp=entry_timestamp,
            entry_price=float(entry_price),
            entry_bar_index=int(entry_bar_index),
            direction=str(direction).upper(),
            symbol=symbol,
            sl=sl_f,
            tp=float(tp) if tp is not None else None,
            original_lot=float(lot),
            remaining_volume=float(lot),
            sl_state=sl_f,
            timeout_bar_index=int(entry_bar_index) + int(max_hold_bars),
            spread=spread,
            max_hold_bars=max_hold_bars,
            exit_mode=mode,
        )

    @property
    def is_buy(self) -> bool:
        return self.direction == "BUY"

    @property
    def risk(self) -> float:
        return _risk_unit(self.entry_price, self.sl)

    def to_exit_info(self) -> dict[str, Any]:
        if not self.closed or self.exit_price is None or self.exit_timestamp is None:
            raise RuntimeError("position not closed")
        exit_ts = pd.to_datetime(self.exit_timestamp, utc=True)
        reason = str(self.close_reason or "timeout").lower()
        return _finalize(
            entry_price=self.entry_price,
            entry_ts=self.entry_timestamp,
            exit_price=float(self.exit_price),
            exit_ts=exit_ts,
            exit_reason=reason,
            is_buy=self.is_buy,
            lot=self.original_lot,
            symbol=self.symbol,
            sl=self.sl,
            tp=self.tp,
            bars_held=self.bars_held,
            mae=self.mae,
            mfe=self.mfe,
            spread=self.spread,
            partial_pnl=self.partial_pnl,
            partial_close_applied=self.partial_executed,
            remaining_lot=self.remaining_volume,
        )


def _close_hybrid_b(state: ReplayPositionState, *, reason: str, price: float, ts: str) -> None:
    final_reason = reason.lower()
    if state.partial_executed and final_reason == "time":
        final_reason = "hybrid_time"
    elif state.partial_executed and final_reason == "sl":
        final_reason = "hybrid_sl"
    state.closed = True
    state.close_reason = final_reason
    state.exit_price = price
    state.exit_timestamp = ts


def advance_hybrid_b_bar(
    state: ReplayPositionState,
    bar: pd.Series,
    bar_index: int,
    bar_timestamp: str,
    *,
    max_candle_index: int,
) -> bool:
    """Advance one bar. Returns True if position closed on this bar."""
    if state.closed or bar_index <= state.entry_bar_index:
        return False
    if bar_index <= state.last_processed_bar:
        return False

    state.last_processed_bar = bar_index
    state.bars_held += 1

    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    risk = state.risk
    entry = state.entry_price
    mult = 1 if state.is_buy else -1

    if risk > 0:
        if state.is_buy:
            state.mfe_r = max(state.mfe_r, (high - entry) / risk)
            state.mae = max(state.mae, max(0.0, (entry - low) / risk))
            state.mfe = max(state.mfe, max(0.0, (high - entry) / risk))
        else:
            state.mfe_r = max(state.mfe_r, (entry - low) / risk)
            state.mae = max(state.mae, max(0.0, (high - entry) / risk))
            state.mfe = max(state.mfe, max(0.0, (entry - low) / risk))

    if not state.partial_executed and state.mfe_r >= PARTIAL_TRIGGER_R:
        partial_price = entry + mult * risk
        state.partial_pnl = _pnl(
            entry,
            partial_price,
            is_buy=state.is_buy,
            lot=state.original_lot * PARTIAL_FRACTION,
            symbol=state.symbol,
        )
        state.remaining_volume = round(state.original_lot * (1.0 - PARTIAL_FRACTION), 4)
        state.partial_executed = True
        state.partial_timestamp = bar_timestamp
        state.partial_price = round(partial_price, 6)

    effective_end = min(state.timeout_bar_index, max_candle_index)
    if bar_index >= effective_end:
        _close_hybrid_b(state, reason="time", price=close, ts=bar_timestamp)
        return True

    broker = PaperBroker()
    hit = broker.resolve_bar(
        bar,
        direction=mult,
        stop_loss=state.sl_state,
        take_profit=entry + mult * 1e9,
    )
    if hit and hit[0].upper() == "SL":
        _close_hybrid_b(state, reason="sl", price=float(hit[1]), ts=bar_timestamp)
        return True

    return False


def advance_current_tp_sl_bar(
    state: ReplayPositionState,
    bar: pd.Series,
    bar_index: int,
    bar_timestamp: str,
    *,
    max_bar_index: int,
) -> bool:
    """Single-bar step for CURRENT TP/SL exit mode."""
    if state.closed or bar_index <= state.entry_bar_index:
        return False
    if bar_index <= state.last_processed_bar:
        return False

    state.last_processed_bar = bar_index
    state.bars_held += 1

    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    risk = state.risk
    entry = state.entry_price
    mult = 1 if state.is_buy else -1

    if risk > 0:
        if state.is_buy:
            state.mae = max(state.mae, max(0.0, (entry - low) / risk))
            state.mfe = max(state.mfe, max(0.0, (high - entry) / risk))
        else:
            state.mae = max(state.mae, max(0.0, (high - entry) / risk))
            state.mfe = max(state.mfe, max(0.0, (entry - low) / risk))

    if bar_index >= max_bar_index:
        state.closed = True
        state.close_reason = "timeout"
        state.exit_price = close
        state.exit_timestamp = bar_timestamp
        return True

    if state.sl is not None and state.tp is not None:
        broker = PaperBroker()
        hit = broker.resolve_bar(
            bar,
            direction=mult,
            stop_loss=state.sl_state,
            take_profit=state.tp,
        )
        if hit:
            state.closed = True
            state.close_reason = str(hit[0]).lower()
            state.exit_price = float(hit[1])
            state.exit_timestamp = bar_timestamp
            return True

    return False


def advance_position_bar(
    state: ReplayPositionState,
    bar: pd.Series,
    bar_index: int,
    bar_timestamp: str,
    *,
    max_candle_index: int,
) -> bool:
    """Dispatch one-bar advance by exit mode. Returns True if closed."""
    if state.exit_mode == ExitMode.HYBRID_B.value:
        return advance_hybrid_b_bar(state, bar, bar_index, bar_timestamp, max_candle_index=max_candle_index)
    end_bar = min(state.entry_bar_index + state.max_hold_bars, max_candle_index)
    return advance_current_tp_sl_bar(
        state, bar, bar_index, bar_timestamp, max_bar_index=end_bar
    )


def simulate_stateful_lifecycle(
    *,
    entry_timestamp: str,
    entry_price: float,
    entry_bar_index: int,
    direction: str,
    symbol: str,
    sl: float | None,
    tp: float | None,
    lot: float,
    candles: pd.DataFrame,
    exit_mode: str | ExitMode = ExitMode.HYBRID_B,
    spread: float = 0.30,
) -> dict[str, Any]:
    """Walk candles bar-by-bar until close — for validation vs resolve_hybrid_b."""
    state = ReplayPositionState.from_open(
        entry_timestamp=entry_timestamp,
        entry_price=entry_price,
        entry_bar_index=entry_bar_index,
        direction=direction,
        symbol=symbol,
        sl=sl,
        tp=tp,
        lot=lot,
        exit_mode=exit_mode,
        spread=spread,
    )
    max_idx = len(candles) - 1
    for j in range(entry_bar_index + 1, max_idx + 1):
        ts = pd.to_datetime(candles.index[j], utc=True).isoformat()
        if advance_position_bar(state, candles.iloc[j], j, ts, max_candle_index=max_idx):
            return state.to_exit_info()

    if not state.closed:
        j = max_idx
        ts = pd.to_datetime(candles.index[j], utc=True).isoformat()
        close = float(candles.iloc[j]["close"])
        _close_hybrid_b(state, reason="time", price=close, ts=ts)
    return state.to_exit_info()
