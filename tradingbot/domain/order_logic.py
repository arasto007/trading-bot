"""
منطق خالصِ اعتبارسنجی و ریسکِ سفارش — معادلِ بخش‌های pure در OrderManager قدیم.

این توابع بدون I/O و بدون MetaTrader5 هستند تا قابل تست و parity باشند. ساختِ
درخواست واقعی و order_send در آداپتر (adapters.mt5_execution) انجام می‌شود.
"""

from __future__ import annotations

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


def order_value(symbol: str, lot_size: float, price: float) -> float:
    """ارزش تقریبی سفارش — دقیقاً مطابق منطق ابزارهای مختلف در نسخه‌ی قدیم."""
    if symbol == "XAUUSD_i":  # طلا
        return lot_size * price * 100
    if symbol == "USDJPY_i":  # جفت‌های ین
        return lot_size * 100_000
    if symbol.endswith("_i"):  # سایر جفت‌های فارکس
        return lot_size * 100_000
    return lot_size * price * 100_000  # سایر ابزارها


def check_order_risk(
    symbol: str,
    lot_size: float,
    price: float,
    max_order_value: float = MAX_ORDER_VALUE,
) -> tuple[bool, str]:
    """بررسی سقف ارزش سفارش (معادل OrderManager._check_order_risk)."""
    value = order_value(symbol, lot_size, price)
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
