"""
لایه میانی سیگنال — نرمال‌سازی خروجی استراتژی به TradingSignal.

مسیر واحد برای:
  - resolve market (symbol / TF / broker / preset)
  - استخراج جهت سیگنال
  - confidence و SL/TP (با fallback یکسان)
  - ساخت TradingSignal نهایی

توابع pure هستند (بدون I/O)؛ resolve_market فقط از config می‌خواند.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedMarket:
    """زمینه بازار پس از resolve — یک‌بار محاسبه، همه‌جا استفاده."""

    symbol: str
    timeframe: str
    legacy_tf: str
    broker_symbol: str
    pa_cfg: dict[str, Any]
    min_confidence: float


def resolve_market(
    market: MarketKey,
    config: dict[str, Any],
    *,
    min_confidence_fallback: float,
) -> ResolvedMarket:
    legacy_tf = to_legacy(market.timeframe)
    broker_symbol = resolve_broker_symbol(market.symbol, config)
    pa_cfg = get_price_action_config(market.symbol, legacy_tf)
    min_conf = float(pa_cfg.get("MIN_CONFIDENCE", min_confidence_fallback))
    return ResolvedMarket(
        symbol=market.symbol,
        timeframe=market.timeframe,
        legacy_tf=legacy_tf,
        broker_symbol=broker_symbol,
        pa_cfg=pa_cfg,
        min_confidence=min_conf,
    )


def extract_signal_direction(signals: pd.Series | None) -> int | None:
    if signals is None or signals.empty:
        return None
    last = int(signals.iloc[-1]) if not pd.isna(signals.iloc[-1]) else 0
    if last == 0:
        return None
    return last


def compute_confidence(
    data: pd.DataFrame,
    signal: int,
    strategy_info: dict,
    *,
    symbol: str = "",
    strategy_name: str = "",
    timeframe: str = "",
) -> float:
    if data.empty or len(data) < 20:
        return 0.5

    pa = (strategy_info or {}).get("priceaction", {})
    conf_meta = pa.get("metadata") or {}
    if conf_meta.get("confidence") is not None:
        return max(0.35, min(float(conf_meta["confidence"]), 1.0))

    confidence = 0.0
    current = data.iloc[-1]
    active = [k for k, v in (strategy_info or {}).items() if abs(v.get("last_signal", 0)) > 0]

    if active == ["priceaction"]:
        last_sig = abs(float(pa.get("last_signal", 0)))
        confidence += 0.50 if last_sig > 0 else 0.35
        if conf_meta.get("confluence"):
            confidence += min(float(conf_meta["confluence"]) * 0.05, 0.25)
    else:
        agreement = min(len(active) / 2.0, 1.0) if active else 0.0
        confidence += agreement * 0.35 + 0.15

    if "sma_20" in data.columns and "sma_50" in data.columns:
        price = current["close"]
        sma_20, sma_50 = current["sma_20"], current["sma_50"]
        if signal == 1 and price > sma_20 > sma_50:
            confidence += 0.25
        elif signal == -1 and price < sma_20 < sma_50:
            confidence += 0.25
        elif (signal == 1 and price > sma_50) or (signal == -1 and price < sma_50):
            confidence += 0.10

    if "volume" in data.columns and len(data) >= 20:
        vol_ratio = current["volume"] / max(data["volume"].tail(20).mean(), 1e-9)
        if vol_ratio > 1.3:
            confidence += 0.15
        elif vol_ratio > 1.0:
            confidence += 0.08

    if "atr" in data.columns and len(data) >= 20:
        atr_ratio = current["atr"] / max(data["atr"].tail(20).mean(), 1e-9)
        if 0.6 < atr_ratio < 1.4:
            confidence += 0.10

    return max(0.35, min(confidence, 1.0))


def confluence_sl_mult_for_tier(account_tier: str | None, *, allow_standard_fallback: bool = True) -> float:
    """Capital-adaptive CONFLUENCE stop width — STANDARD preserves production default."""
    if account_tier is None:
        if allow_standard_fallback:
            tier = "STANDARD"
        else:
            return 2.2
    else:
        tier = account_tier.upper()
    if tier == "MICRO":
        return 1.1
    if tier == "SMALL":
        return 1.5
    return 2.2


def confluence_tp_rr_for_tier(account_tier: str | None, *, allow_standard_fallback: bool = True) -> float:
    """Capital-adaptive CONFLUENCE reward/risk — STANDARD preserves production default."""
    if account_tier is None:
        if allow_standard_fallback:
            tier = "STANDARD"
        else:
            return 1.6
    else:
        tier = account_tier.upper()
    if tier == "MICRO":
        return 1.4
    return 1.6


def compress_micro_stop_pips(
    stop_distance_pips: float,
    atr_pct: float | None,
) -> float:
    """Compress wide MICRO stops to improve min-lot feasibility (XAUUSD only)."""
    if stop_distance_pips <= 18:
        return stop_distance_pips
    if atr_pct is None:
        return stop_distance_pips
    if stop_distance_pips <= 30:
        return 18.0
    if stop_distance_pips <= 50:
        return 15.0
    return 12.0


def _is_live_runtime() -> bool:
    import os

    return os.environ.get("TRADINGBOT_LIVE", "").lower() in ("1", "true", "yes")


def compute_sl_tp(
    data: pd.DataFrame,
    signal: int,
    confidence: float,
    *,
    symbol: str = "",
    strategy_name: str = "",
    timeframe: str = "",
    config: dict[str, Any] | None = None,
    strategy_info: dict | None = None,
    account_tier: str | None = None,
    atr_pct: float | None = None,
) -> tuple[float, float, dict[str, Any]]:
    if data.empty:
        return 0.0, 0.0, {}

    pa = (strategy_info or {}).get("priceaction", {})
    meta = pa.get("metadata") or {}
    sl_m = meta.get("stop_loss")
    tp_m = meta.get("take_profit")
    if sl_m is not None and tp_m is not None:
        extra = {k: v for k, v in meta.items() if k not in ("stop_loss", "take_profit")}
        return float(sl_m), float(tp_m), extra

    pa_cfg = (config or {}).get("PRICE_ACTION", {})
    price = float(data["close"].iloc[-1])
    atr = _atr(data, symbol=symbol)
    sym = symbol.upper()
    live_no_tier = _is_live_runtime() and account_tier is None
    tier_fallback = not live_no_tier

    if live_no_tier:
        logger.warning(
            "Live tier unknown — capital-adaptive SL disabled; using strategy/config defaults"
        )

    if strategy_name == "vol_regime":
        sl_mult = 2.0
        rr = 1.25
    elif strategy_name in ("high_vol_momentum",):
        sl_mult = 3.0
        rr = 1.35
    elif strategy_name in ("mtf_trend", "confluence"):
        if strategy_name == "mtf_trend":
            sl_mult = 2.5
            rr = 1.5
        else:
            sl_mult = confluence_sl_mult_for_tier(
                account_tier, allow_standard_fallback=tier_fallback
            )
            rr = confluence_tp_rr_for_tier(
                account_tier, allow_standard_fallback=tier_fallback
            )
    else:
        sl_mult = float(pa_cfg.get("SL_ATR_MULT", 1.5))
        rr = float(pa_cfg.get("TP_RR", 2.5))

        if "XAU" in sym or "GOLD" in sym:
            sl_mult = max(sl_mult, 2.0)
            rr = max(rr, 2.5)
        elif "JPY" in sym:
            sl_mult = max(sl_mult, 1.8)
            rr = max(rr, 2.2)

    if signal == 1:
        sl = price - atr * sl_mult
        tp = price + (price - sl) * rr
    else:
        sl = price + atr * sl_mult
        tp = price - (sl - price) * rr

    tier_upper = (account_tier or "").upper()
    if tier_upper == "MICRO":
        from tradingbot.domain.position_logic import pip_size as ps_fn

        ps = ps_fn(symbol or PRIMARY_SYMBOL)
        stop_pips = abs(price - sl) / ps if ps > 0 else 0.0
        atr_pct_val = atr_pct
        if atr_pct_val is None and strategy_info:
            meta = (strategy_info or {}).get("priceaction", {}).get("metadata") or {}
            raw = meta.get("atr_pct")
            atr_pct_val = float(raw) if raw is not None else None
        compressed = compress_micro_stop_pips(stop_pips, atr_pct_val)
        if compressed + 0.01 < stop_pips:
            logger.info(
                "MICRO stop compressed in compute_sl_tp | %sp -> %sp",
                round(stop_pips, 1),
                round(compressed, 1),
            )
            if signal == 1:
                sl = price - compressed * ps
            else:
                sl = price + compressed * ps
            rr = 1.2
            if signal == 1:
                tp = price + (price - sl) * rr
            else:
                tp = price - (sl - price) * rr

    return float(sl), float(tp), {}


def build_trading_signal(
    market: MarketKey,
    df: pd.DataFrame,
    signals: pd.Series | None,
    strategy_info: dict | None,
    config: dict[str, Any],
    *,
    primary_strategy: str,
    min_confidence_fallback: float,
) -> TradingSignal | None:
    if df is None or df.empty:
        return None

    direction_raw = extract_signal_direction(signals)
    if direction_raw is None:
        return None

    resolved = resolve_market(market, config, min_confidence_fallback=min_confidence_fallback)
    info = strategy_info or {}

    confidence = compute_confidence(
        df,
        direction_raw,
        info,
        symbol=market.symbol,
        strategy_name=primary_strategy,
        timeframe=market.timeframe,
    )
    if confidence < resolved.min_confidence:
        logger.debug(
            "Signal filtered: confidence %.2f < %.2f (preset=%s)",
            confidence,
            resolved.min_confidence,
            resolved.pa_cfg.get("PRESET"),
        )
        return None

    sl, tp, extra_meta = compute_sl_tp(
        df,
        direction_raw,
        confidence,
        symbol=market.symbol,
        strategy_name=primary_strategy,
        timeframe=market.timeframe,
        config=config,
        strategy_info=info,
    )

    direction = SignalDirection.BUY if direction_raw > 0 else SignalDirection.SELL

    return TradingSignal(
        direction=direction,
        confidence=confidence,
        symbol=market.symbol,
        timeframe=market.timeframe,
        strategy_name=primary_strategy,
        stop_loss=sl,
        take_profit=tp,
        metadata={
            "strategy_info": info,
            "broker_symbol": resolved.broker_symbol,
            **extra_meta,
        },
    )


def _atr(data: pd.DataFrame, symbol: str = "", period: int = 14) -> float:
    if "atr" in data.columns and not pd.isna(data["atr"].iloc[-1]):
        return float(data["atr"].iloc[-1])
    high, low, close = data["high"], data["low"], data["close"]
    tr = pd.concat(
        [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    val = tr.rolling(period, min_periods=period).mean().iloc[-1]
    price = float(close.iloc[-1])
    return float(val) if not pd.isna(val) and val > 0 else price * 0.001
