"""منطق سشن، اسپرد و بستن پوزیشن — مشترک live و backtest."""

from __future__ import annotations

from datetime import datetime

from tradingbot.domain.position_logic import pip_size


def in_trading_session(ts: datetime, start_hour: int, end_hour: int) -> bool:
    hour = ts.hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def spread_pips_from_prices(ask: float, bid: float, symbol: str) -> float:
    if ask <= 0 or bid <= 0 or ask < bid:
        return 999.0
    return (ask - bid) / pip_size(symbol)


def spread_ok(spread_pips: float, max_spread_pips: float) -> bool:
    return spread_pips <= max_spread_pips


def session_cost_multiplier(hour: int) -> float:
    if 12 <= hour < 17:
        return 1.0
    if 8 <= hour < 12 or 17 <= hour < 21:
        return 1.25
    if 0 <= hour < 7:
        return 1.6
    return 1.4


def variable_spread_pips(base_spread: float, hour: int) -> float:
    return round(base_spread * session_cost_multiplier(hour), 2)


def variable_slippage_pips(base_slippage: float, hour: int) -> float:
    return round(base_slippage * session_cost_multiplier(hour), 2)


def is_friday(ts: datetime) -> bool:
    return ts.weekday() == 4


def friday_no_new_entries(ts: datetime, *, no_entry_after_hour: int = 17) -> bool:
    return is_friday(ts) and ts.hour >= no_entry_after_hour


def should_friday_close(
    ts: datetime, *, close_hour: int = 20, close_minute: int = 0
) -> bool:
    if not is_friday(ts):
        return False
    return ts.hour > close_hour or (ts.hour == close_hour and ts.minute >= close_minute)


def should_eod_close(ts: datetime, *, eod_hour: int = 23, eod_minute: int = 55) -> bool:
    return ts.hour > eod_hour or (ts.hour == eod_hour and ts.minute >= eod_minute)


def is_kill_zone(ts: datetime, *, use_kill_zones: bool = True) -> bool:
    """
    پنجره‌های پرحجم ICT (UTC):
      London: 07:00–10:00
      New York: 12:00–15:00
    """
    if not use_kill_zones:
        return True
    h = ts.hour
    return (7 <= h < 10) or (12 <= h < 15)
