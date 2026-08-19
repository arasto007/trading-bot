"""
منطق خالص مدیریت پوزیشن — مشترک بین live و backtest.

این توابع هیچ وابستگی به MT5 یا I/O ندارند تا هم در آداپتر زنده
(``Mt5PositionManager``) و هم در بک‌تست (``BacktestPositionManager``)
دقیقاً یکسان استفاده شوند. (Single Source of Truth)
"""

from __future__ import annotations


def pip_size(symbol: str) -> float:
    """اندازه pip بر اساس نوع نماد (heuristic مطابق پروژه‌ی قدیم + طلا)."""
    s = symbol.upper()
    if "JPY" in s:
        return 0.01
    if "XAU" in s or "GOLD" in s:
        return 0.1
    return 0.0001


def contract_size(symbol: str) -> float:
    """
    پول (به ارز حساب) به ازای ۱.۰ واحد حرکت قیمت برای ۱.۰ لات.

    تقریبی برای بک‌تست:
      - طلا (XAUUSD): 100 (۱ لات = ۱۰۰ اونس)
      - جفت‌های JPY: 1000
      - فارکس استاندارد: 100,000 (پس ۱ pip روی ۰.۰۱ لات ≈ ۰.۱ دلار)
    """
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        return 100.0
    if "JPY" in s:
        return 1000.0
    return 100_000.0


def calculate_safe_sl(
    is_buy: bool,
    entry: float,
    current_price: float,
    profit_pips: float,
    pip: float,
    original_sl: float,
    atr: float,
) -> float:
    """
    Trailing Stop پلکانی ATR-Based — بازسازی دقیق ``_calculate_aggressive_sl`` قدیم.

    مراحل (به pip سود):
      0–8:    SL = ورود ∓ ۵
      8–15:   SL = نقطه سربه‌سر
      15–30:  فاصله = max(2.0×ATR, 12)
      30–50:  فاصله = max(1.5×ATR, 10)
      50–100: فاصله = max(1.2×ATR, 8)
      100+:   فاصله = max(1.0×ATR, 8)

    SL هرگز شل نمی‌شود (یک‌طرفه به نفع سود).
    """
    atr_pips = max(3.0, min(atr / pip, 50.0)) if pip > 0 else 10.0

    if profit_pips < 8:
        base = entry - 5 * pip if is_buy else entry + 5 * pip
        distance = None
    elif profit_pips < 15:
        base = entry  # breakeven
        distance = None
    elif profit_pips < 30:
        base, distance = None, max(atr_pips * 2.0, 12.0)
    elif profit_pips < 50:
        base, distance = None, max(atr_pips * 1.5, 10.0)
    elif profit_pips < 100:
        base, distance = None, max(atr_pips * 1.2, 8.0)
    else:
        base, distance = None, max(atr_pips * 1.0, 8.0)

    if is_buy:
        calculated = base if base is not None else current_price - distance * pip
        return max(original_sl, calculated)
    calculated = base if base is not None else current_price + distance * pip
    return min(original_sl, calculated) if original_sl > 0 else calculated


def trailing_improves(is_buy: bool, original_sl: float, new_sl: float) -> bool:
    """آیا SL جدید بهبود (سفت‌تر به نفع سود) است؟"""
    if is_buy:
        return new_sl > original_sl
    return (original_sl <= 0) or (0 < new_sl < original_sl)


# سطوح پیش‌فرض Partial TP: (مضرب R، درصد حجمی که بسته می‌شود)
DEFAULT_PARTIAL_TP_LEVELS: tuple[tuple[float, float], ...] = (
    (1.0, 0.50),
    (2.0, 0.30),
    (3.0, 0.20),
)


def partial_tp_target(is_buy: bool, entry: float, risk: float, r_multiple: float) -> float:
    """قیمت هدف برای یک سطح Partial TP (بر اساس مضرب R = |entry − SL|)."""
    return entry + r_multiple * risk if is_buy else entry - r_multiple * risk


def target_hit(is_buy: bool, current_price: float, target: float) -> bool:
    return current_price >= target if is_buy else current_price <= target
