"""
اندیکاتورهای تکنیکال — توابع خالص (pure functions).

این ماژول نسخه‌ی تمیز و بازنویسی‌شده‌ی منطق اندیکاتورهاست که جایگزین
`engine/features.py` می‌شود. عمداً **رفتار-سازگار (parity)** با نسخه‌ی قدیم نوشته
شده تا سیگنال استراتژی‌ها تغییر نکند:

- همان مجموعه‌ی ۲۲ ستون خروجی
- همان فرمول‌ها و پارامترها (RSI ساده، ADX/ATR با rolling-mean، `min_periods=1`)
- همان cast نهایی به float32 و همان مرحله‌ی پاکسازی (ffill → bfill → fillna(0))

توابع اینجا هیچ I/O، لاگ یا وابستگی بیرونی ندارند؛ فقط DataFrame می‌گیرند و
DataFrame برمی‌گردانند. این باعث می‌شود تست و بازنگری ساده باشد و در آینده بتوان
فرمول‌ها را تک‌به‌تک مدرن کرد بدون اینکه چیز دیگری بشکند.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

#: حداقل تعداد کندل لازم برای محاسبه (کمتر از این، داده دست‌نخورده برمی‌گردد).
MIN_BARS = 50

#: ستون‌های ضروری ورودی.
REQUIRED_COLUMNS = ("open", "high", "low", "close")

#: پارامترهای پیش‌فرض (مطابق نسخه‌ی قدیم).
DEFAULT_PARAMS: dict[str, Any] = {
    "rsi_window": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "adx_window": 14,
    "atr_window": 14,
    "sma_short": 20,
    "sma_long": 50,
    "z_score_window": 20,
    "roc_period": 12,
}

#: فهرست کامل ستون‌هایی که این ماژول تولید می‌کند.
INDICATOR_COLUMNS: tuple[str, ...] = (
    "rsi",
    "macd",
    "macd_signal",
    "macd_histogram",
    "adx",
    "plus_di",
    "minus_di",
    "atr",
    "atrp",
    "sma_20",
    "sma_50",
    "ema_20",
    "ema_50",
    "z_score",
    "roc",
    "bb_upper",
    "bb_middle",
    "bb_lower",
    "bb_bandwidth",
    "bb_percent_b",
    "stoch_k",
    "stoch_d",
)

_F32 = np.float32


# --------------------------------------------------------------------------- #
# اعتبارسنجی و پارامترها
# --------------------------------------------------------------------------- #
def validate(df: pd.DataFrame) -> bool:
    """آیا داده برای محاسبه‌ی اندیکاتورها مناسب است؟ (مطابق منطق قدیم)."""
    if df is None or df.empty:
        return False
    if len(df) < MIN_BARS:
        return False
    if any(col not in df.columns for col in REQUIRED_COLUMNS):
        return False
    if df["close"].isna().any():
        return False
    return True


def resolve_params(
    config: dict[str, Any] | None = None,
    timeframe: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """
    ادغام پارامترهای پیش‌فرض با override های موجود در `config['strategy_params']`.

    ترتیب دقیقاً مطابق نسخه‌ی قدیم: default → timeframe → symbol → gbpusd_override.
    """
    params = dict(DEFAULT_PARAMS)
    strategy_params = (config or {}).get("strategy_params")
    if isinstance(strategy_params, dict):
        if timeframe and timeframe in strategy_params:
            params.update(strategy_params[timeframe])
        if symbol and symbol in strategy_params:
            params.update(strategy_params[symbol])
        if symbol == "GBPUSD_i" and "gbpusd_override" in params:
            params.update(params["gbpusd_override"])
    return params


# --------------------------------------------------------------------------- #
# helper مشترک
# --------------------------------------------------------------------------- #
def _true_range(df: pd.DataFrame) -> pd.Series:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)


# --------------------------------------------------------------------------- #
# اندیکاتورها (هرکدام ستون‌های خود را به df اضافه می‌کند)
# --------------------------------------------------------------------------- #
def add_rsi(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gains = gains.rolling(window=window, min_periods=1).mean()
    avg_losses = losses.rolling(window=window, min_periods=1).mean()
    rs = avg_gains / np.where(avg_losses == 0, np.nan, avg_losses)
    df["rsi"] = (100 - (100 / (1 + rs))).astype(_F32)
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    df["macd"] = macd.astype(_F32)
    df["macd_signal"] = macd_signal.astype(_F32)
    df["macd_histogram"] = (macd - macd_signal).astype(_F32)
    return df


def add_adx(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    tr = _true_range(df)
    atr = tr.rolling(window=window, min_periods=1).mean()

    plus_dm = df["high"].diff()
    minus_dm = -df["low"].diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    plus_di = 100 * (plus_dm.rolling(window=window, min_periods=1).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=window, min_periods=1).mean() / atr)

    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    df["adx"] = dx.rolling(window=window, min_periods=1).mean().astype(_F32)
    df["plus_di"] = plus_di.astype(_F32)
    df["minus_di"] = minus_di.astype(_F32)
    return df


def add_atr(df: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    tr = _true_range(df)
    atr = tr.rolling(window=window, min_periods=1).mean()
    df["atr"] = atr.astype(_F32)
    df["atrp"] = ((atr / df["close"]) * 100).astype(_F32)
    return df


def add_moving_averages(df: pd.DataFrame, short: int = 20, long: int = 50) -> pd.DataFrame:
    df["sma_20"] = df["close"].rolling(window=short, min_periods=1).mean().astype(_F32)
    df["sma_50"] = df["close"].rolling(window=long, min_periods=1).mean().astype(_F32)
    df["ema_20"] = df["close"].ewm(span=short, adjust=False).mean().astype(_F32)
    df["ema_50"] = df["close"].ewm(span=long, adjust=False).mean().astype(_F32)
    return df


def add_z_score(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    rolling_mean = df["close"].rolling(window=window, min_periods=1).mean()
    rolling_std = df["close"].rolling(window=window, min_periods=1).std()
    df["z_score"] = ((df["close"] - rolling_mean) / rolling_std).astype(_F32)
    return df


def add_roc(df: pd.DataFrame, period: int = 12) -> pd.DataFrame:
    df["roc"] = (df["close"].pct_change(periods=period) * 100).astype(_F32)
    return df


def add_bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    middle = df["close"].rolling(window=window, min_periods=1).mean()
    std = df["close"].rolling(window=window, min_periods=1).std()
    upper = middle + std * num_std
    lower = middle - std * num_std
    df["bb_upper"] = upper.astype(_F32)
    df["bb_middle"] = middle.astype(_F32)
    df["bb_lower"] = lower.astype(_F32)
    df["bb_bandwidth"] = ((upper - lower) / middle * 100).astype(_F32)
    df["bb_percent_b"] = ((df["close"] - lower) / (upper - lower)).astype(_F32)
    return df


def add_stochastic(df: pd.DataFrame, k_window: int = 14, d_window: int = 3) -> pd.DataFrame:
    lowest_low = df["low"].rolling(window=k_window, min_periods=1).min()
    highest_high = df["high"].rolling(window=k_window, min_periods=1).max()
    stoch_k = ((df["close"] - lowest_low) / (highest_high - lowest_low)) * 100
    df["stoch_k"] = stoch_k.astype(_F32)
    df["stoch_d"] = stoch_k.rolling(window=d_window, min_periods=1).mean().astype(_F32)
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """پُرکردن NaNها: ffill → bfill → صفر برای ستون‌های عددی (مطابق قدیم)."""
    df = df.ffill().bfill()
    numeric = df.select_dtypes(include=[np.number]).columns
    df[numeric] = df[numeric].fillna(0)
    return df


# --------------------------------------------------------------------------- #
# هماهنگ‌کننده‌ی اصلی
# --------------------------------------------------------------------------- #
def compute_indicators(
    df: pd.DataFrame,
    *,
    params: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    timeframe: str | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """
    افزودن همه‌ی اندیکاتورها به DataFrame ورودی.

    اگر داده نامعتبر/کم باشد، همان DataFrame دست‌نخورده برمی‌گردد (مثل نسخه‌ی قدیم).
    `params` صریح بر `config` ارجح است؛ اگر هیچ‌کدام نباشد، پیش‌فرض‌ها استفاده می‌شوند.
    """
    if not validate(df):
        return df

    if params is None:
        params = resolve_params(config, timeframe, symbol)

    out = df.copy()
    out = add_rsi(out, params.get("rsi_window", 14))
    out = add_macd(
        out,
        params.get("macd_fast", 12),
        params.get("macd_slow", 26),
        params.get("macd_signal", 9),
    )
    out = add_adx(out, params.get("adx_window", 14))
    out = add_atr(out, params.get("atr_window", 14))
    out = add_moving_averages(out, params.get("sma_short", 20), params.get("sma_long", 50))
    out = add_z_score(out, params.get("z_score_window", 20))
    out = add_roc(out, params.get("roc_period", 12))
    out = add_bollinger_bands(out, params.get("bb_window", 20), params.get("bb_std", 2))
    out = add_stochastic(
        out, params.get("stoch_k_window", 14), params.get("stoch_d_window", 3)
    )
    return clean(out)
