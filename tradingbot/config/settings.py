"""
KernelSettings — تنظیمات هسته‌ی معاملاتی (معماری جدید، Ports & Adapters).

این dataclass سبک، ورودی پیکربندیِ `TradingKernel` است و از پیکربندی legacy
(`engine_settings`/`live`) جداست؛ تبدیل در `tradingbot.config.legacy_settings`
انجام می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KernelSettings:
    """تنظیمات اجرای هسته."""

    symbols: list[str]
    timeframes: list[str]
    base_dir: Path = field(default_factory=lambda: Path("."))
    cycle_interval_seconds: float = 60.0
    initial_balance: float = 10_000.0
    data_cache_ttl: int = 300
    enabled_strategies: dict[str, bool] = field(default_factory=dict)
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
