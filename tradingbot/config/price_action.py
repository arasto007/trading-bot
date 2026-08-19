"""پیکربندی Price Action حرفه‌ای — SMC / structure / liquidity."""

from __future__ import annotations

import copy
from typing import Any

from tradingbot.config.pa_symbol_tf_presets import get_symbol_tf_overrides

# Single source of truth for PA bar cooldown (live RiskGate + backtest + runtime truth).
PA_COOLDOWN_BARS = 18

PRICE_ACTION_CONFIG: dict[str, Any] = {
    # Active preset: quality — بهترین نتیجه ماتریس ۶۰روزه XAUUSD (M15 +25.5%, H1 +26.2%)
    "PRESET": "quality",
    # Market structure
    "SWING_LEFT": 3,
    "SWING_RIGHT": 3,
    "FVG_LOOKBACK": 80,
    "ATR_PERIOD": 14,
    # Risk — فیلتر کیفیت (ICT/SMC حرفه‌ای)
    "SL_ATR_MULT": 2.0,
    "MIN_RR": 2.2,
    "TP_RR": 2.2,
    "MIN_CONFLUENCE": 2.8,
    "MIN_CONFIDENCE": 0.58,
    # Session (UTC) — لندن تا پایان نیویورک (۸–۲۰)
    "SESSION_START_HOUR": 8,
    "SESSION_END_HOUR": 20,
    # Risk gates (live + backtest)
    "MAX_DAILY_LOSS_PCT": 0.04,
    "MAX_TRADES_PER_DAY": 0,  # 0 = unlimited (no daily cap)
    "MAX_CONSECUTIVE_LOSSES": 3,
    "COOLDOWN_AFTER_LOSS_BARS": 20,
    "COOLDOWN_BARS": PA_COOLDOWN_BARS,
    "MIN_BALANCE_PCT": 0.70,
    "MAX_SPREAD_PIPS": 5.0,
    "USE_NEWS_FILTER": True,
    "NEWS_BLACKOUT_MINUTES": 30,
    "MAX_OPEN_POSITIONS_TOTAL": 3,
    "MAX_OPEN_POSITIONS_PER_SYMBOL": 2,
    "REQUIRE_HTF_ALIGNMENT_M5": False,
    "REQUIRE_HTF_ALIGNMENT_M15": False,
    "REQUIRE_HTF_ALIGNMENT_H4": False,
    "USE_KILL_ZONES": False,
    "SIGNAL_CONFIRMATION_BARS": 0,
    "USE_PREMIUM_DISCOUNT": False,
    "REQUIRE_SWEEP_BEFORE_ENTRY": False,
    "PREFER_CHOCH": False,
    "USE_REGIME_FILTER": False,
    "MAX_DRAWDOWN_PCT": 0.15,
    "FRIDAY_CLOSE_ENABLED": True,
    "FRIDAY_CLOSE_HOUR": 20,
    "FRIDAY_CLOSE_MINUTE": 0,
    "FRIDAY_NO_ENTRY_AFTER_HOUR": 17,
    "TRAILING_ATR_MULT": 2.0,
    "EOD_CLOSE_ENABLED": True,
    "EOD_HOUR": 21,
    "EOD_MINUTE": 55,
    "MIN_BARS": 80,
    "SIGNAL_WINDOW_BARS": 300,
    "FETCH_BARS": 300,
    "ALLOWED_SYMBOLS": ["XAUUSD", "XAUUSD_I", "GOLD"],
    "DEFAULT_TIMEFRAMES": ["5m", "15m", "4h"],
}


def get_price_action_config(symbol: str = "", timeframe: str = "") -> dict[str, Any]:
    """پایه + override اختصاصی نماد/تایم‌فریم."""
    cfg = copy.deepcopy(PRICE_ACTION_CONFIG)
    overrides = get_symbol_tf_overrides(symbol, timeframe)
    preset = overrides.get("PRESET", cfg.get("PRESET", "quality"))
    for k, v in overrides.items():
        cfg[k] = v
    cfg["PRESET"] = preset
    return cfg


def apply_pa_to_legacy(legacy: dict[str, Any], symbol: str, timeframe: str) -> dict[str, Any]:
    """legacy config را برای بک‌تست/live با پریست همان TF هم‌راستا می‌کند."""
    merged = dict(legacy)
    pa = get_price_action_config(symbol, timeframe)
    merged["PRICE_ACTION"] = pa
    merged["MIN_CONFIDENCE"] = pa["MIN_CONFIDENCE"]
    merged["MAX_TRADES_PER_DAY"] = pa.get("MAX_TRADES_PER_DAY", merged.get("MAX_TRADES_PER_DAY", 5))
    for key in (
        "MAX_OPEN_POSITIONS_TOTAL",
        "MAX_OPEN_POSITIONS_PER_SYMBOL",
        "USE_NEWS_FILTER",
        "MAX_SPREAD_PIPS",
        "COOLDOWN_BARS",
    ):
        if key in pa:
            merged[key] = pa[key]
    merged.setdefault("COOLDOWN_BARS", int(pa.get("COOLDOWN_BARS", PA_COOLDOWN_BARS)))
    return merged
