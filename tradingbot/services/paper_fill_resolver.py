"""Resolve paper fill prices without requiring a live MT5 tick."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import TradingSignal
from tradingbot.ml.paper_trading.paper_broker import PaperBroker

logger = logging.getLogger(__name__)


def _is_valid_price(price: float | None) -> bool:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return False
    return value > 0 and value == value


def _direction_int(direction: SignalDirection) -> int:
    if direction == SignalDirection.BUY:
        return 1
    if direction == SignalDirection.SELL:
        return -1
    return 0


def _mt5_quote(signal: TradingSignal, config: dict[str, Any] | None) -> float:
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.symbols import resolve_broker_symbol

        cfg = config or {}
        broker_symbol = resolve_broker_symbol(signal.symbol, cfg)
        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return 0.0
        price = float(tick.ask if signal.direction == SignalDirection.BUY else tick.bid)
        return price if _is_valid_price(price) else 0.0
    except Exception:
        return 0.0


def _candle_close(
    signal: TradingSignal,
    base_dir: str | Path | None,
    *,
    bar_time: pd.Timestamp | None = None,
) -> float:
    try:
        from tradingbot.ml.data.stores.candle_store import CandleStore

        candles = CandleStore(base_dir).load(signal.symbol, signal.timeframe)
        if candles is None or candles.empty:
            return 0.0
        frame = candles.copy()
        if not isinstance(frame.index, pd.DatetimeIndex):
            if "time" in frame.columns:
                frame = frame.set_index("time")
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
        if bar_time is not None:
            ts = pd.Timestamp(bar_time, tz="UTC")
            pos = int(frame.index.searchsorted(ts))
            pos = min(max(pos, 0), len(frame) - 1)
            close = float(frame.iloc[pos]["close"])
            return close if _is_valid_price(close) else 0.0
        close = float(frame.iloc[-1]["close"])
        return close if _is_valid_price(close) else 0.0
    except Exception as exc:
        logger.debug("candle close fallback failed: %s", exc)
        return 0.0


def _sl_tp_midpoint(signal: TradingSignal) -> float:
    sl = signal.stop_loss
    tp = signal.take_profit
    if sl is None or tp is None:
        return 0.0
    mid = (float(sl) + float(tp)) / 2.0
    return mid if mid > 0 else 0.0


def resolve_paper_fill(
    signal: TradingSignal,
    *,
    base_dir: str | Path | None = None,
    config: dict[str, Any] | None = None,
    mt5_price: float | None = None,
    bar_time: pd.Timestamp | None = None,
) -> tuple[float, float, str]:
    """
    Resolve paper fill price using fallback chain:
    MT5 tick -> CandleStore close -> SL/TP midpoint.

    Returns (fill_price, spread, source_tag).
    """
    direction = _direction_int(signal.direction)
    if direction == 0:
        return 0.0, 0.0, "hold"

    broker = PaperBroker()
    spread = float(broker.config.spread_points)

    raw = float(mt5_price) if mt5_price is not None else 0.0
    source = "mt5_tick"
    if not _is_valid_price(raw):
        raw = _mt5_quote(signal, config)
    if not _is_valid_price(raw):
        raw = _candle_close(signal, base_dir, bar_time=bar_time)
        source = "candle_close"
    if not _is_valid_price(raw):
        raw = _sl_tp_midpoint(signal)
        source = "sl_tp_midpoint"

    if not _is_valid_price(raw):
        logger.warning(
            "paper fill unresolved for %s %s — no MT5 tick, candle, or SL/TP midpoint",
            signal.symbol,
            signal.direction.name,
        )
        return 0.0, spread, "unresolved"

    fill = broker.execute_entry(raw, direction)
    if source == "mt5_tick":
        return fill.fill_price, spread, source
    return fill.fill_price, spread, source
