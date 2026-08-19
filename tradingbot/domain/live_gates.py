"""
گیت‌های ریسک live — توابع pure مشترک با بک‌تست.

spread، خبر، حد پوزیشن، جمعه، HTF alignment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from tradingbot.domain.news_logic import is_news_blackout
from tradingbot.domain.session_logic import friday_no_new_entries, spread_ok


def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().replace("_I", "").replace(".M", "")
    if s in ("GOLD", "XAU"):
        return "XAUUSD"
    return s


def position_matches_symbol(position: Any, symbol: str) -> bool:
    if isinstance(position, dict):
        raw = position.get("symbol", "")
    else:
        raw = getattr(position, "symbol", "")
    pos_sym = normalize_symbol(str(raw))
    return pos_sym == normalize_symbol(symbol)


def count_open_positions(
    positions: list[Any],
    *,
    symbol: str | None = None,
) -> int:
    if not positions:
        return 0
    if symbol is None:
        return len(positions)
    return sum(1 for p in positions if position_matches_symbol(p, symbol))


def check_max_positions(
    open_total: int,
    open_symbol: int,
    *,
    max_total: int,
    max_per_symbol: int,
) -> tuple[bool, str]:
    if max_total > 0 and open_total >= max_total:
        return False, f"max total positions ({open_total}>={max_total})"
    if max_per_symbol > 0 and open_symbol >= max_per_symbol:
        return False, f"max positions for symbol ({open_symbol}>={max_per_symbol})"
    return True, "ok"


def check_spread_gate(spread_pips: float, max_spread_pips: float) -> tuple[bool, str]:
    if spread_pips >= 999:
        return False, "spread unavailable"
    if not spread_ok(spread_pips, max_spread_pips):
        return False, f"spread too high ({spread_pips:.1f}>{max_spread_pips:.1f} pips)"
    return True, "ok"


def check_news_gate(
    ts: datetime | None,
    *,
    enabled: bool,
    minutes: int,
) -> tuple[bool, str]:
    if not enabled or ts is None:
        return True, "ok"
    if is_news_blackout(ts, minutes_before=minutes, minutes_after=minutes):
        return False, "news blackout"
    return True, "ok"


def check_friday_gate(
    ts: datetime | None,
    *,
    no_entry_after_hour: int,
) -> tuple[bool, str]:
    if ts is None:
        return True, "ok"
    if friday_no_new_entries(ts, no_entry_after_hour=no_entry_after_hour):
        return False, "friday no entry window"
    return True, "ok"


def check_htf_alignment(
    signal_direction: int,
    htf_bias: int,
    *,
    required: bool,
) -> tuple[bool, str]:
    if not required or htf_bias == 0:
        return True, "ok"
    if signal_direction != htf_bias:
        return False, f"HTF bias mismatch (signal={signal_direction} htf={htf_bias})"
    return True, "ok"


def _position_direction(position: Any) -> int:
    if isinstance(position, dict):
        if position.get("is_buy") is True:
            return 1
        if position.get("is_buy") is False:
            return -1
        raw = position.get("type", position.get("direction"))
        if raw in (0, "buy", "BUY"):
            return 1
        if raw in (1, "sell", "SELL", -1):
            return -1
        return 0
    raw = getattr(position, "type", None)
    if raw is not None:
        # MT5: 0=BUY, 1=SELL
        return 1 if int(raw) == 0 else -1 if int(raw) == 1 else 0
    if getattr(position, "is_buy", None) is True:
        return 1
    if getattr(position, "is_buy", None) is False:
        return -1
    return 0


def check_no_opposite_position(
    signal_direction: int,
    positions: list[Any],
    *,
    symbol: str,
) -> tuple[bool, str]:
    """Block hedging — no new entry opposite to an open position on same symbol."""
    if signal_direction == 0:
        return True, "ok"
    for pos in positions:
        if not position_matches_symbol(pos, symbol):
            continue
        pos_dir = _position_direction(pos)
        if pos_dir != 0 and pos_dir != signal_direction:
            return False, "opposite direction position open"
    return True, "ok"
