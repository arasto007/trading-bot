"""
ویژگی‌های واقعی ورود به معامله — منبع واحد برای meta-labeler و لاگ لایو.

همه مقادیر از سیگنال/اسنپ‌شات لحظه ورود گرفته می‌شوند؛ بدون placeholder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from tradingbot.domain.market_filters import atr_percentile, compute_adx
from tradingbot.domain.models import TradingSignal
from tradingbot.domain.position_logic import contract_size

# ویژگی‌های ثابت — منبع واحد Phase D1 (Meta-Labeler + ML Kernel)
from tradingbot.ml.features.unified_feature_store import FEATURES as FEATURE_NAMES

REGIME_MAP: dict[str, float] = {
    "STRONG_TREND_UP": 1.0,
    "STRONG_TREND_DOWN": -1.0,
    "RANGING": 0.0,
    "VOLATILE": 0.5,
    "CRISIS": -0.5,
}

SETUP_MAP: dict[str, float] = {
    "liquidity_sweep": 1.0,
    "LIQUIDITY_SWEEP": 1.0,
    "order_block": 2.0,
    "ORDER_BLOCK": 2.0,
    "fvg": 3.0,
    "FVG": 3.0,
    "bos": 4.0,
    "BOS": 4.0,
    "swing": 5.0,
    "SWING": 5.0,
    "intraday": 6.0,
    "unknown": 0.0,
}


def _meta_from_signal(signal: TradingSignal) -> dict[str, Any]:
    meta = dict(signal.metadata or {})
    info = meta.get("strategy_info") or {}
    pa = info.get("priceaction") or {}
    pa_meta = pa.get("metadata") or {}
    merged = {**pa_meta, **{k: v for k, v in meta.items() if k != "strategy_info"}}
    return merged


def _setup_code(meta: dict[str, Any]) -> float:
    raw = meta.get("setup") or meta.get("setup_type") or meta.get("GOLD_STRATEGY_MODE") or "unknown"
    return SETUP_MAP.get(str(raw), 0.0)


def _sl_atr_mult(
    entry: float,
    sl: float | None,
    df: pd.DataFrame | None,
) -> float:
    if not sl or sl <= 0 or entry <= 0 or df is None or df.empty:
        return 0.0
    dist = abs(entry - sl)
    if dist <= 0:
        return 0.0
    if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]):
        atr = float(df["atr"].iloc[-1])
    else:
        closed = df.iloc[:-1] if len(df) > 1 else df
        if len(closed) < 14:
            return 0.0
        high, low, close = closed["high"], closed["low"], closed["close"]
        tr = pd.concat(
            [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
            axis=1,
        ).max(axis=1)
        atr = float(tr.rolling(14, min_periods=14).mean().iloc[-1])
    if atr <= 0:
        return 0.0
    return round(dist / atr, 4)


def capture_entry_features(
    signal: TradingSignal,
    snapshot: dict[str, Any],
    regime: str,
    *,
    spread_pips: float = 0.0,
    entry_price: float | None = None,
) -> dict[str, float]:
    """استخراج ویژگی واقعی در لحظه تأیید ورود."""
    meta = _meta_from_signal(signal)
    df = snapshot.get("ohlcv")
    closed = None
    adx = 0.0
    atr_pct = 50.0
    if isinstance(df, pd.DataFrame) and len(df) > 30:
        closed = df.iloc[:-1] if len(df) > 1 else df
        adx = compute_adx(closed)
        atr_pct = atr_percentile(closed)

    ts = snapshot.get("current_time")
    hour = 12.0
    weekday = 2.0
    if ts is not None:
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if isinstance(ts, datetime):
            hour = float(ts.hour)
            weekday = float(ts.weekday())

    entry = entry_price or float(getattr(signal, "entry_price", None) or meta.get("entry") or 0.0)
    if entry <= 0 and isinstance(df, pd.DataFrame) and not df.empty:
        entry = float(df["close"].iloc[-1])

    conf_meta = meta.get("confidence")
    confidence = float(conf_meta if conf_meta is not None else signal.confidence or 0.0)
    confluence = float(meta.get("confluence", 0.0) or 0.0)
    rr = float(meta.get("risk_reward_ratio", meta.get("rr", 0.0)) or 0.0)
    if rr <= 0 and signal.stop_loss and signal.take_profit and entry > 0:
        risk = abs(entry - float(signal.stop_loss))
        reward = abs(float(signal.take_profit) - entry)
        if risk > 0:
            rr = round(reward / risk, 4)

    return {
        "confidence": round(confidence, 4),
        "confluence": round(confluence, 4),
        "rr": round(rr, 4),
        "adx": round(adx, 4),
        "atr_pct": round(atr_pct, 4),
        "htf_bias": float(snapshot.get("htf_bias", 0) or 0),
        "hour_utc": hour,
        "weekday": weekday,
        "direction": 1.0 if signal.direction.name == "BUY" else -1.0,
        "regime_code": REGIME_MAP.get(regime, 0.0),
        "spread_pips": round(float(spread_pips), 4),
        "sl_atr_mult": _sl_atr_mult(entry, signal.stop_loss, closed if closed is not None else df),
        "setup_code": _setup_code(meta),
    }


def features_to_vector(features: dict[str, float]) -> list[float]:
    from tradingbot.ml.features.unified_feature_store import to_vector

    return to_vector(features)


def r_multiple(
    pnl: float,
    entry_price: float,
    sl: float | None,
    volume: float,
    symbol: str,
    is_buy: bool,
) -> float:
    """مضرب R واقعی معامله (بعد از بسته شدن)."""
    if sl is None or sl <= 0 or volume <= 0 or entry_price <= 0:
        return 0.0 if pnl <= 0 else 1.0
    risk_per_unit = abs(entry_price - sl) * contract_size(symbol)
    risk_money = risk_per_unit * volume
    if risk_money <= 0:
        return 0.0
    return pnl / risk_money


def trade_quality_label(
    pnl: float,
    entry_price: float,
    sl: float | None,
    volume: float,
    symbol: str,
    is_buy: bool,
    *,
    min_r: float = 0.35,
) -> int:
    """
    برچسب کیفیت: ۱ فقط اگر سودده با حداقل min_r برابر ریسک اولیه.
    ضررها و بردهای ناچیز (scalp بد) = ۰.
    """
    if pnl <= 0:
        return 0
    r = r_multiple(pnl, entry_price, sl, volume, symbol, is_buy)
    return 1 if r >= min_r else 0


def estimate_spread_pips(
    symbol: str,
    spread_pips_cfg: float,
    hour: int,
    *,
    variable: bool = True,
) -> float:
    from tradingbot.domain.session_logic import variable_spread_pips

    if variable:
        return variable_spread_pips(spread_pips_cfg, hour)
    return spread_pips_cfg
