"""تنظیمات مدیریت پوزیشن per symbol/TF — parity بک‌تست و live."""

from __future__ import annotations

from tradingbot.adapters.timeframes import to_legacy
from tradingbot.config.price_action import get_price_action_config

_TF_ALIASES = {
    "5M": "M5",
    "15M": "M15",
    "4H": "H4",
    "M5": "M5",
    "M15": "M15",
    "H4": "H4",
}


def normalize_tf(timeframe: str) -> str:
    t = (timeframe or "").upper()
    return _TF_ALIASES.get(t, t)


def partial_tp_enabled(symbol: str, timeframe: str) -> bool:
    """آیا partial TP برای این TF فعال است (از پریست PA)."""
    pa = get_price_action_config(symbol, to_legacy(timeframe))
    return bool(pa.get("ENABLE_PARTIAL_TP", False))


def parse_timeframe_from_comment(comment: str) -> str | None:
    """
    استخراج TF از کامنت MT5.

    فرمت جدید: TB_M15_priceaction
    """
    if not comment:
        return None
    parts = str(comment).split("_")
    if len(parts) >= 2 and parts[0] == "TB":
        tf = normalize_tf(parts[1])
        if tf in ("M5", "M15", "H4"):
            return tf
    return None
