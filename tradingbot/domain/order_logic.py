"""
منطق خالصِ اعتبارسنجی و ریسکِ سفارش — معادلِ بخش‌های pure در OrderManager قدیم.

این توابع بدون I/O و بدون MetaTrader5 هستند تا قابل تست و parity باشند. ساختِ
درخواست واقعی و order_send در آداپتر (adapters.mt5_execution) انجام می‌شود.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tradingbot.domain.broker_economics import BrokerEconomics

#: سقف ارزش سفارش (دلار) — همان مقدار ثابت OrderManager قدیم.
MAX_ORDER_VALUE = 100_000


def validate_order(
    symbol: str,
    expected_symbol: str,
    signal: int,
    lot_size: float,
    price: float,
) -> tuple[bool, str]:
    """اعتبارسنجی پارامترهای سفارش (معادل OrderManager._validate_order)."""
    if symbol != expected_symbol:
        return False, f"Symbol mismatch: {symbol} vs {expected_symbol}"
    if signal not in (1, -1):
        return False, f"Invalid signal: {signal}"
    if lot_size <= 0:
        return False, f"Invalid lot size: {lot_size}"
    if price <= 0:
        return False, f"Invalid price: {price}"
    return True, "ok"


def order_value(
    symbol: str,
    lot_size: float,
    price: float,
    *,
    economics: BrokerEconomics | None = None,
) -> float:
    """
    Approximate order notional for cap checks.

    Phase 25A: uses broker contract_size when economics provided.
    Without economics, returns 0 (fail-closed for cap — callers must supply economics).
    """
    if economics is not None:
        return economics.order_notional(lot_size, price)
    return 0.0


def check_order_risk(
    symbol: str,
    lot_size: float,
    price: float,
    max_order_value: float = MAX_ORDER_VALUE,
    *,
    economics: BrokerEconomics | None = None,
) -> tuple[bool, str]:
    """بررسی سقف ارزش سفارش (معادل OrderManager._check_order_risk)."""
    if economics is None:
        return False, "BROKER_ECONOMICS_REQUIRED"
    value = order_value(symbol, lot_size, price, economics=economics)
    if value <= 0:
        return False, "INVALID_ORDER_NOTIONAL"
    if value > max_order_value:
        return False, f"Order value too large: ${value:,.2f}"
    return True, "ok"


def filling_mode_name(filling_flag: int) -> str:
    """نگاشت پرچم filling_mode نماد به نام حالت (مطابق نسخه‌ی قدیم)."""
    if filling_flag == 1:
        return "FOK"
    if filling_flag == 2:
        return "IOC"
    return "RETURN"
