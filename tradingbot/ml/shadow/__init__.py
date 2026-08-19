"""Phase 10 — ML shadow integration with TradingKernel observation (no orders)."""

from tradingbot.ml.shadow.config import ShadowConfig
from tradingbot.ml.shadow.ml_adapter import MLAdapter, MLPrediction
from tradingbot.ml.shadow.shadow_engine import MLShadowEngine, MLShadowResult
from tradingbot.ml.shadow.shadow_signal import ShadowSignal

__all__ = [
    "MLAdapter",
    "MLPrediction",
    "MLShadowEngine",
    "MLShadowResult",
    "ShadowConfig",
    "ShadowSignal",
]
