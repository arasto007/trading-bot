"""فیلترهای کیفیت بازار — ADX، ATR percentile، رژیم (با تطبیق خودکار)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.risk_logic import infer_regime_from_ohlcv, regime_blocks_entry


def compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """ADX آخرین کندل بسته (بدون look-ahead)."""
    if df is None or df.empty or len(df) < period + 2:
        return 0.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.rolling(period).mean()
    val = adx.iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def atr_percentile(df: pd.DataFrame, lookback: int = 252) -> float:
    """صدک ATR فعلی نسبت به lookback کندل اخیر (0-100)."""
    if df is None or df.empty or len(df) < 20:
        return 50.0
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_series = tr.rolling(14).mean().dropna()
    if atr_series.empty:
        return 50.0
    window = atr_series.tail(min(lookback, len(atr_series)))
    current = float(window.iloc[-1])
    return float((window < current).sum() / max(len(window) - 1, 1) * 100)


def adapt_filters_for_regime(cfg: dict[str, Any], regime: str) -> dict[str, Any]:
    """آستانه‌ها را بر اساس رژیم بازار نرم/سخت می‌کند."""
    if not bool(cfg.get("REGIME_ADAPTIVE_FILTERS", True)):
        return cfg
    out = dict(cfg)
    r = regime or "RANGING"
    if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        out["ATR_PCT_MIN"] = max(10, float(out.get("ATR_PCT_MIN", 18)) - 6)
        out["ADX_MIN_FOR_ENTRY"] = max(10, float(out.get("ADX_MIN_FOR_ENTRY", 15)) - 3)
        out["ATR_PCT_MAX"] = min(95, float(out.get("ATR_PCT_MAX", 82)) + 5)
    elif r == "VOLATILE":
        out["ATR_PCT_MIN"] = max(8, float(out.get("ATR_PCT_MIN", 18)) - 8)
        out["ATR_PCT_MAX"] = min(96, float(out.get("ATR_PCT_MAX", 82)) + 10)
        out["ADX_MIN_FOR_ENTRY"] = max(8, float(out.get("ADX_MIN_FOR_ENTRY", 15)) - 5)
    elif r == "RANGING":
        out["ATR_PCT_MIN"] = max(12, float(out.get("ATR_PCT_MIN", 18)) - 2)
        out["ADX_MIN_FOR_ENTRY"] = max(12, float(out.get("ADX_MIN_FOR_ENTRY", 15)) - 2)
    elif r == "CRISIS":
        out["ATR_PCT_MIN"] = max(15, float(out.get("ATR_PCT_MIN", 18)))
        out["ATR_PCT_MAX"] = min(88, float(out.get("ATR_PCT_MAX", 82)) - 4)
    return out


def check_market_filters(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None = None,
    *,
    strategy_mode: str = "",
) -> tuple[bool, str]:
    """
    فیلترهای rule-based — با تطبیق رژیم.

    london_sweep: فقط ATR extreme + regime volatile
    intraday/h4_swing: ADX + ATR + regime
    """
    cfg = cfg or {}
    if not bool(cfg.get("USE_MARKET_FILTERS", True)):
        return True, "ok"

    if df is None or df.empty or len(df) < 30:
        return False, "insufficient data for market filters"

    closed = df.iloc[:-1] if len(df) > 1 else df
    regime = infer_regime_from_ohlcv(closed)
    cfg = adapt_filters_for_regime(cfg, regime)

    if bool(cfg.get("USE_REGIME_FILTER", False)):
        mode = (strategy_mode or cfg.get("GOLD_STRATEGY_MODE", "")).lower()
        if regime_blocks_entry(regime, strategy_mode=mode):
            return False, f"regime blocked ({regime})"

    if bool(cfg.get("USE_ATR_PERCENTILE_FILTER", True)):
        pct_min = float(cfg.get("ATR_PCT_MIN", 25))
        pct_max = float(cfg.get("ATR_PCT_MAX", 80))
        pct = atr_percentile(closed)
        if pct < pct_min:
            return False, f"ATR percentile too low ({pct:.0f}<{pct_min:.0f})"
        if pct > pct_max:
            return False, f"ATR percentile too high ({pct:.0f}>{pct_max:.0f})"

    mode = (strategy_mode or cfg.get("GOLD_STRATEGY_MODE", "")).lower()
    use_adx = bool(cfg.get("USE_ADX_FILTER", mode in ("intraday", "h4_swing")))
    if use_adx:
        adx_min = float(cfg.get("ADX_MIN_FOR_ENTRY", 20))
        adx = compute_adx(closed, int(cfg.get("ADX_PERIOD", 14)))
        if adx < adx_min:
            return False, f"ADX too low ({adx:.1f}<{adx_min:.1f})"

    return True, "ok"
