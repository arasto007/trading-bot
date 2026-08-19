"""
shim سازگاری — منبع حقیقتِ پیکربندی به `tradingbot.config.engine_settings` منتقل شد.

ماژول‌های قدیمی engine هنوز `from engine.config import config / create_config` می‌کنند؛
این shim همان نام‌ها را از مکان جدید دوباره صادر می‌کند تا چیزی نشکند.
"""

from __future__ import annotations

from tradingbot.config.engine_settings import *  # noqa: F401,F403
from tradingbot.config.engine_settings import (  # noqa: F401
    TradingBotConfig,
    config,
    create_config,
)
