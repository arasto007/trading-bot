"""Phase 10.1/10.2 — real ML shadow integration with TradingKernel."""

from tradingbot.ml.integration.composite_registry import CompositeStrategyRegistry
from tradingbot.ml.integration.config import KernelShadowConfig, is_ml_shadow_enabled, is_ml_shadow_mode
from tradingbot.ml.integration.kernel_shadow_runner import KernelShadowRunner, KernelShadowResult
from tradingbot.ml.integration.live_shadow_runner import LiveShadowConfig, LiveShadowRunner, LiveShadowResult
from tradingbot.ml.integration.ml_strategy import MLShadowStrategy, STRATEGY_NAME
from tradingbot.ml.integration.shadow_execution_guard import ShadowExecutionGuard
from tradingbot.ml.integration.sl_tp_calculator import ATRTradeCalculator
from tradingbot.ml.integration.trade_integrity import TradeIntegrityValidator
from tradingbot.ml.integration.virtual_trade_builder import VirtualTradeBuilder

__all__ = [
    "CompositeStrategyRegistry",
    "KernelShadowConfig",
    "KernelShadowResult",
    "KernelShadowRunner",
    "LiveShadowConfig",
    "LiveShadowResult",
    "LiveShadowRunner",
    "MLShadowStrategy",
    "STRATEGY_NAME",
    "ShadowExecutionGuard",
    "ATRTradeCalculator",
    "TradeIntegrityValidator",
    "VirtualTradeBuilder",
    "is_ml_shadow_enabled",
    "is_ml_shadow_mode",
]
