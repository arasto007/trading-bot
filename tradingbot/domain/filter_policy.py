"""
سیاست فیلترها — هر فیلتر فقط یک‌بار و در لایه درست اعمال می‌شود.

لایه ۱ (استراتژی): سشن، کیفیت setup، min confidence
لایه ۲ (ریسک ساختاری): spread، خبر، جمعه، max position، cooldown
لایه ۳ (کیفیت بازار): regime + ADX + ATR — فقط RiskGate
لایه ۴: HTF alignment
لایه ۵: Meta-labeler per-TF
"""

from __future__ import annotations

import os
from typing import Any

# DEMO ONLY — set DEMO_DISABLE_SESSION_FILTER=true in .env to bypass session windows.
# Re-enable before any live/prop deployment.
_DEMO_SESSION_DISABLED = os.getenv("DEMO_DISABLE_SESSION_FILTER", "").lower() in (
    "1",
    "true",
    "yes",
)

# فیلترهایی که نباید در استراتژی تکرار شوند (فقط RiskGate)
RISK_ONLY_FLAGS = frozenset(
    {
        "USE_REGIME_FILTER",
        "USE_MARKET_FILTERS",
        "USE_ADX_FILTER",
        "USE_ATR_PERCENTILE_FILTER",
    }
)


def is_session_filter_enabled(cfg: dict[str, Any] | None = None) -> bool:
    """False when demo testing disables London/NY session windows."""
    if cfg and cfg.get("DEMO_DISABLE_SESSION_FILTER") is not None:
        return not bool(cfg.get("DEMO_DISABLE_SESSION_FILTER"))
    if _DEMO_SESSION_DISABLED:
        return False
    return True


def demo_session_override_active() -> bool:
    """True when session windows are bypassed for demo testing."""
    return not is_session_filter_enabled()


def strategy_uses_kill_zone(cfg: dict[str, Any]) -> bool:
    """اگر سشن NY/London صریح تعریف شده، kill zone اضافی لازم نیست."""
    if bool(cfg.get("M5_USE_NY_SESSION")) or bool(cfg.get("M5_USE_LONDON_SESSION")):
        return False
    return bool(cfg.get("USE_KILL_ZONES", False))


def aligned_session_hours(cfg: dict[str, Any]) -> tuple[int, int]:
    """ساعت سشن هم‌راستا با پنجره ورود استراتژی."""
    mode = str(cfg.get("GOLD_STRATEGY_MODE", "")).lower()
    if mode == "london_sweep":
        if bool(cfg.get("M5_USE_NY_SESSION")):
            return (
                int(cfg.get("NY_ENTRY_START_UTC", cfg.get("NY_ENTRY_START_HOUR", 12))),
                int(cfg.get("NY_ENTRY_END_UTC", cfg.get("NY_ENTRY_END_HOUR", 15))),
            )
        if bool(cfg.get("M5_USE_LONDON_SESSION")):
            return (
                int(cfg.get("LONDON_ENTRY_START_HOUR", 7)),
                int(cfg.get("LONDON_ENTRY_END_HOUR", 10)),
            )
    return (
        int(cfg.get("SESSION_START_HOUR", 8)),
        int(cfg.get("SESSION_END_HOUR", 20)),
    )
