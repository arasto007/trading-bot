"""سیم‌کشی هسته — demo (stub) یا live (MT5 legacy adapters)."""

from __future__ import annotations

import asyncio
import logging
import os
from enum import Enum

from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.adapters.risk_gate import create_risk_gate
from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter
from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter
from tradingbot.adapters.mt5_position_manager import Mt5PositionManager
from tradingbot.adapters.stubs import (
    StubExecutor,
    StubIndicators,
    StubMarketData,
    StubRisk,
    StubStrategies,
)
from tradingbot.config.legacy_settings import kernel_settings_from_legacy
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.settings import KernelSettings
from tradingbot.kernel.trading_kernel import TradingKernel
from tradingbot.ml.integration.factory import build_strategy_registry

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


class KernelMode(str, Enum):
    DEMO = "demo"
    LIVE_MT5 = "live_mt5"


def build_kernel(
    mode: KernelMode = KernelMode.DEMO,
    settings: KernelSettings | None = None,
) -> TradingKernel:
    if mode == KernelMode.LIVE_MT5:
        return build_kernel_live(settings)
    return build_kernel_demo(settings)


def build_kernel_demo(settings: KernelSettings | None = None) -> TradingKernel:
    settings = settings or KernelSettings(
        symbols=[PRIMARY_SYMBOL],
        timeframes=["M5", "M15"],
        cycle_interval_seconds=1.0,
    )
    return TradingKernel(
        settings=settings,
        market_data=StubMarketData(),
        indicators=StubIndicators(),
        strategies=StubStrategies(),
        risk=StubRisk(),
        executor=StubExecutor(),
    )


def build_kernel_live(settings: KernelSettings | None = None) -> TradingKernel:
    """هسته live: MT5 + استراتژی + RiskManager legacy + مدیریت پوزیشن هسته‌محور."""
    settings = settings or kernel_settings_from_legacy()
    legacy_config = settings.extra or {}
    risk_gate = create_risk_gate(legacy_config)
    base_dir = legacy_config.get("BASE_DIR")

    return TradingKernel(
        settings=settings,
        market_data=Mt5MarketDataAdapter(legacy_config),
        indicators=TechnicalIndicatorEngine(legacy_config),
        strategies=build_strategy_registry(legacy_config, base_dir=base_dir),
        risk=risk_gate,
        executor=Mt5ExecutionAdapter(legacy_config),
        position_manager=Mt5PositionManager(legacy_config),
    )


def build_kernel_with_strategies(settings: KernelSettings | None = None) -> TradingKernel:
    """تست کامل pipeline با استراتژی + ریسک legacy (بدون MT5)."""
    settings = settings or KernelSettings(
        symbols=[PRIMARY_SYMBOL],
        timeframes=["M5", "M15"],
    )
    legacy_config = load_legacy_config_for_strategies()
    risk_gate = create_risk_gate(legacy_config)
    base_dir = legacy_config.get("BASE_DIR")

    return TradingKernel(
        settings=settings,
        market_data=StubMarketData(),
        indicators=TechnicalIndicatorEngine(legacy_config),
        strategies=build_strategy_registry(legacy_config, base_dir=base_dir),
        risk=risk_gate,
        executor=StubExecutor(),
    )


def load_legacy_config_for_strategies() -> dict:
    from tradingbot.adapters.legacy_loader import load_legacy_config

    return load_legacy_config()


def run_demo_cycle() -> None:
    kernel = build_kernel_demo()
    results = asyncio.run(kernel.run_global_cycle())
    _print_cycle_results(kernel, results)


def run_strategies_cycle() -> None:
    """دمو با استراتژی‌های واقعی (بدون MT5)."""
    kernel = build_kernel_with_strategies()
    logger.info("Mode: STRATEGIES (stub data + active strategies)")
    results = asyncio.run(kernel.run_global_cycle())
    _print_cycle_results(kernel, results)


def run_live_cycle(*, dry_run: bool = True, paper: bool = False) -> None:
    """
    یک چرخه با MT5 واقعی.

    dry_run=True: فقط اتصال + داده؛ سفارش واقعی ارسال نمی‌شود
    paper=True: تیک واقعی + پر کردن شبیه‌سازی‌شده در journal
    dry_run=False و paper=False: اجرای سفارش واقعی
    """
    os.environ.pop("TRADINGBOT_DRY_RUN", None)
    os.environ.pop("TRADINGBOT_PAPER", None)
    if paper:
        os.environ["TRADINGBOT_PAPER"] = "1"
    elif dry_run:
        os.environ["TRADINGBOT_DRY_RUN"] = "1"

    kernel = build_kernel_live()
    from tradingbot.services.execution_mode import mode_label

    logger.info("Mode: LIVE_MT5 | mode=%s", mode_label())
    results = asyncio.run(kernel.run_global_cycle())
    _print_cycle_results(kernel, results)


def _print_cycle_results(kernel: TradingKernel, results: dict) -> None:
    for key, ctx in results.items():
        sig = ctx.signal.direction.name if ctx.signal else "none"
        err = "; ".join(ctx.errors) if ctx.errors else "ok"
        print(f"  {key} -> signal={sig} | {err}")
    print(f"Pipeline stages: {kernel.pipeline_stages}")
