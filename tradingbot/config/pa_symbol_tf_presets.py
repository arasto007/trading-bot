"""پریست‌های تخصصی طلا — M5 NY sweep | M15 intraday | H4 swing.

سیاست فیلتر (بدون تداخل):
  M5: سشن NY 15-16 UTC | Asian end 08:00 | ATR adaptive | بدون ADX
  M15: سشن 7-21 | premium/discount | HTF H4 | meta تطبیقی
  H4: 24h | premium/discount | sweep | HTF D1
"""

from __future__ import annotations

from typing import Any

PA_SYMBOL_TF_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "XAUUSD": {
        "M5": {
            "PRESET": "gold_ny_sweep",
            "GOLD_STRATEGY_MODE": "london_sweep",
            "MIN_CONFIDENCE": 0.52,
            "MIN_RR": 1.5,
            "TP_RR": 1.5,
            "SL_ATR_MULT": 0.35,
            "ASIAN_START_HOUR": 0,
            "ASIAN_END_HOUR": 8,
            "ASIAN_SESSION_END_UTC": 8,
            "M5_USE_LONDON_SESSION": False,
            "M5_USE_NY_SESSION": True,
            "NY_ENTRY_START_HOUR": 15,
            "NY_ENTRY_END_HOUR": 16,
            "NY_ENTRY_START_UTC": 15,
            "NY_ENTRY_END_UTC": 16,
            "SWEEP_LOOKBACK_BARS": 12,
            "SWEEP_BUFFER_ATR": 0.12,
            "MIN_RANGE_ATR": 0.2,
            "M5_REQUIRE_REJECTION": False,
            "COOLDOWN_BARS": 18,
            "MAX_TRADES_PER_DAY": 3,
            "SESSION_START_HOUR": 15,
            "SESSION_END_HOUR": 16,
            "USE_KILL_ZONES": False,
            "REQUIRE_HTF_ALIGNMENT_M5": False,
            "USE_REGIME_FILTER": True,
            "USE_MARKET_FILTERS": True,
            "REGIME_ADAPTIVE_FILTERS": True,
            "USE_ADX_FILTER": False,
            "USE_ATR_PERCENTILE_FILTER": True,
            "ATR_PCT_MIN": 12,
            "ATR_PCT_MAX": 94,
            "ENABLE_PARTIAL_TP": False,
            "META_LABEL_THRESHOLD": 0.38,
            "MAX_OPEN_POSITIONS_TOTAL": 3,
            "MAX_OPEN_POSITIONS_PER_SYMBOL": 2,
            "ENABLE_BOS_CONTINUATION": True,
            "ENABLE_CHOCH_CONTINUATION": False,
            "ENABLE_FVG_CONFIRMATION": True,
            "ENABLE_LIQUIDITY_SWEEP_DETECTOR": True,
            "ENABLE_SESSION_RANGE_STATS": True,
            "MIN_QUALITY_SCORE": 55,
            "PA_DEDUP_COOLDOWN_MINUTES": 10,
        },
        "M15": {
            "PRESET": "atr_tight_gold",
            "GOLD_STRATEGY_MODE": "intraday",
            "SL_ATR_MULT": 1.6,
            "MIN_RR": 2.0,
            "TP_RR": 2.0,
            "MIN_CONFLUENCE": 2.3,
            "MIN_CONFIDENCE": 0.52,
            "COOLDOWN_BARS": 6,
            "MAX_TRADES_PER_DAY": 4,
            "SESSION_START_HOUR": 7,
            "SESSION_END_HOUR": 21,
            "USE_KILL_ZONES": False,
            "SIGNAL_CONFIRMATION_BARS": 0,
            "USE_PREMIUM_DISCOUNT": True,
            "REQUIRE_SWEEP_BEFORE_ENTRY": True,
            "USE_REGIME_FILTER": True,
            "USE_MARKET_FILTERS": True,
            "REGIME_ADAPTIVE_FILTERS": True,
            "USE_ADX_FILTER": True,
            "ADX_MIN_FOR_ENTRY": 12,
            "ATR_PCT_MIN": 12,
            "ATR_PCT_MAX": 88,
            "REQUIRE_HTF_ALIGNMENT_M15": True,
            "ENABLE_PARTIAL_TP": True,
            "META_LABEL_THRESHOLD": 0.40,
            "MAX_OPEN_POSITIONS_TOTAL": 3,
            "MAX_OPEN_POSITIONS_PER_SYMBOL": 2,
        },
        "H4": {
            "PRESET": "gold_h4_swing",
            "GOLD_STRATEGY_MODE": "h4_swing",
            "SWING_LEFT": 3,
            "SWING_RIGHT": 3,
            "FVG_LOOKBACK": 100,
            "SL_ATR_MULT": 1.8,
            "MIN_RR": 2.0,
            "TP_RR": 2.0,
            "MIN_CONFLUENCE": 2.3,
            "MIN_CONFIDENCE": 0.50,
            "COOLDOWN_BARS": 6,
            "MAX_TRADES_PER_DAY": 2,
            "SESSION_START_HOUR": 0,
            "SESSION_END_HOUR": 24,
            "USE_KILL_ZONES": False,
            "H4_ALLOW_FVG": True,
            "H4_REQUIRE_TREND_ALIGN": False,
            "USE_PREMIUM_DISCOUNT": True,
            "REQUIRE_SWEEP_BEFORE_ENTRY": True,
            "USE_REGIME_FILTER": True,
            "USE_MARKET_FILTERS": True,
            "REGIME_ADAPTIVE_FILTERS": True,
            "USE_ADX_FILTER": False,
            "REQUIRE_HTF_ALIGNMENT_H4": True,
            "ENABLE_PARTIAL_TP": False,
            "META_LABEL_THRESHOLD": 0.38,
            "MAX_OPEN_POSITIONS_TOTAL": 2,
            "MAX_OPEN_POSITIONS_PER_SYMBOL": 1,
        },
    },
}

PA_ALLOWED_TIMEFRAMES: frozenset[str] = frozenset({"M5", "M15", "H4"})


def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().replace("_I", "").replace(".M", "")
    return "XAUUSD" if s in ("GOLD", "XAU", "XAUUSD") else s


def normalize_timeframe(timeframe: str) -> str:
    t = (timeframe or "M15").upper()
    return {
        "5M": "M5",
        "15M": "M15",
        "4H": "H4",
        "M5": "M5",
        "M15": "M15",
        "H4": "H4",
    }.get(t, t)


def is_pa_cell_enabled(symbol: str, timeframe: str) -> bool:
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    return sym == "XAUUSD" and tf in PA_ALLOWED_TIMEFRAMES


def get_symbol_tf_overrides(symbol: str, timeframe: str) -> dict[str, Any]:
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    return dict(PA_SYMBOL_TF_PRESETS.get(sym, {}).get(tf, {}))


def get_active_preset_name(symbol: str, timeframe: str) -> str:
    ov = get_symbol_tf_overrides(symbol, timeframe)
    return str(ov.get("PRESET", "quality"))
