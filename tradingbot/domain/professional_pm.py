"""Phase 52A professional position management — pure helpers (live + backtest)."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.domain.position_logic import pip_size, trailing_improves


@dataclass(frozen=True)
class ProfessionalPmState:
    breakeven_done: bool = False
    partial_done: bool = False
    trailing_active: bool = False
    bars_since_open: int = 0


def current_r(*, is_buy: bool, entry: float, price: float, risk: float) -> float:
    if risk <= 0:
        return 0.0
    move = (price - entry) if is_buy else (entry - price)
    return move / risk


def breakeven_sl(*, is_buy: bool, entry: float, spread: float) -> float:
    return entry + spread if is_buy else entry - spread


def trail_distance(*, atr: float, pip: float, atr_multiplier: float, min_pips: float) -> float:
    """Trailing distance in price units: max(atr_multiplier * ATR, min_pips * pip)."""
    min_dist = max(float(min_pips), 0.0) * pip
    atr_dist = max(float(atr_multiplier), 0.0) * max(float(atr), 0.0)
    return max(atr_dist, min_dist)


def atr_trail_sl(
    *,
    is_buy: bool,
    current_price: float,
    original_sl: float,
    atr: float,
    pip: float,
    atr_multiplier: float,
    min_pips: float,
) -> float | None:
    """Compute improved ATR trail SL; None if no improvement."""
    dist = trail_distance(atr=atr, pip=pip, atr_multiplier=atr_multiplier, min_pips=min_pips)
    new_sl = current_price - dist if is_buy else current_price + dist
    if not trailing_improves(is_buy, original_sl, new_sl):
        return None
    return new_sl


def should_breakeven(*, current_r: float, trigger_r: float, done: bool) -> bool:
    return not done and current_r >= trigger_r


def should_partial(*, current_r: float, trigger_r: float, done: bool) -> bool:
    return not done and current_r >= trigger_r


def should_trail(
    *,
    current_r: float,
    trigger_r: float,
    partial_done: bool,
    requires_partial: bool,
) -> bool:
    if requires_partial and not partial_done:
        return False
    return current_r >= trigger_r


def should_time_stop(
    *,
    bars_since_open: int,
    current_r: float,
    bars_limit: int,
    min_profit_r: float,
) -> bool:
    return bars_since_open >= bars_limit and current_r < min_profit_r


def partial_close_volume(volume: float, fraction: float = 0.5, min_lot: float = 0.01) -> float:
    close = round(volume * fraction, 2)
    remaining = round(volume - close, 2)
    if remaining < min_lot:
        return 0.0
    return close


def bar_atr_from_ohlc(high: float, low: float, close: float, pip: float) -> float:
    """Fallback ATR proxy from single bar when series unavailable."""
    return max(high - low, pip * 10)


def compute_atr14(bars: list[dict], pip: float, period: int = 14) -> float:
    """Simple ATR14 from OHLC bar dicts with high/low/close keys."""
    if len(bars) < 2:
        return pip * 10
    trs: list[float] = []
    for i in range(1, len(bars)):
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if not trs:
        return pip * 10
    window = trs[-period:]
    return float(sum(window) / len(window))
