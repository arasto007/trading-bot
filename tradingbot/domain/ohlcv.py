"""
نرمال‌سازی OHLCV — تابع خالص.

ستون‌های ورودی (از MT5 یا کش) را به فرمت استاندارد هسته تبدیل می‌کند:
`open, high, low, close, volume` با ایندکس زمانی. نگاشت حجم از
`tick_volume`/`real_volume` پشتیبانی می‌شود.

این منطق قبلاً درون `Mt5MarketDataAdapter._normalize_ohlcv` بود و اکنون به‌صورت
تابع خالص و مستقل اینجا قرار دارد (بدون I/O، قابل تست).
"""

from __future__ import annotations

import pandas as pd

#: ستون‌هایی که برای استخراج «حجم» امتحان می‌شوند (به‌ترتیب اولویت).
VOLUME_COLUMNS: tuple[str, ...] = ("volume", "tick_volume", "real_volume")

_REQUIRED = ("open", "high", "low", "close")


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame خام را به `[open, high, low, close, volume]` با ایندکس زمانی تبدیل می‌کند.

    - اگر ستون `time` موجود و ایندکس زمانی نیست، آن را ایندکس می‌کند.
    - نام ستون‌های OHLC را به حروف کوچک یکدست می‌کند.
    - اگر `volume` نبود، از `tick_volume`/`real_volume` می‌سازد؛ وگرنه صفر.
    - ردیف‌های دارای NaN در ستون‌های لازم حذف می‌شوند.

    اگر هرکدام از ستون‌های OHLC پیدا نشوند، `ValueError` می‌دهد.
    """
    out = df.copy()

    if out.index.name != "time" and "time" in out.columns:
        out = out.set_index("time")

    rename = {
        col: str(col).lower()
        for col in out.columns
        if str(col).lower() in _REQUIRED
    }
    if rename:
        out = out.rename(columns=rename)

    if "volume" not in out.columns:
        for vc in VOLUME_COLUMNS:
            if vc in out.columns:
                out["volume"] = out[vc]
                break
        else:
            out["volume"] = 0

    missing = [c for c in _REQUIRED if c not in out.columns]
    if missing:
        raise ValueError(f"OHLCV missing columns: {missing}")

    return out[list(_REQUIRED) + ["volume"]].dropna()


def exclude_forming_bar(df: pd.DataFrame, *, min_rows: int = 60) -> pd.DataFrame | None:
    """
    آخرین کندل MT5 معمولاً در حال تشکیل است — برای سیگنال حذفش می‌کنیم.

    بک‌تست فقط روی کندل‌های بسته‌شده ارزیابی می‌کند؛ live باید همین‌طور باشد.
    """
    if df is None or df.empty or len(df) < min_rows + 1:
        return None
    return df.iloc[:-1].copy()
