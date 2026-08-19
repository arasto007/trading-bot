"""تبدیل config قدیم به KernelSettings."""

from __future__ import annotations

from pathlib import Path

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.timeframes import to_kernel
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.settings import KernelSettings
from tradingbot.config.strategies import ACTIVE_STRATEGIES


def kernel_settings_from_legacy() -> KernelSettings:
    cfg = load_legacy_config()
    symbols = cfg.get("SYMBOLS") or cfg.get("symbols") or [PRIMARY_SYMBOL]
    timeframes = cfg.get("TIMEFRAMES") or cfg.get("timeframes") or ["15m"]
    cfg["enabled_strategies"] = dict(ACTIVE_STRATEGIES)

    return KernelSettings(
        base_dir=Path(cfg.get("BASE_DIR", ".")),
        symbols=list(symbols),
        timeframes=[to_kernel(tf) for tf in timeframes],
        cycle_interval_seconds=float(cfg.get("LOOP_INTERVAL", 60)),
        initial_balance=float(cfg.get("initial_balance", 10_000)),
        data_cache_ttl=int(cfg.get("data_cache_ttl", 300)),
        enabled_strategies=dict(ACTIVE_STRATEGIES),
        mt5_login=cfg.get("MT5_LOGIN"),
        mt5_password=cfg.get("MT5_PASSWORD"),
        mt5_server=cfg.get("MT5_SERVER"),
        extra=cfg,
    )
