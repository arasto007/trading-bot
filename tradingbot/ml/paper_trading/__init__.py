"""Phase 9.10 — paper trading & shadow validation."""

from tradingbot.ml.paper_trading.model_registry import (
    Phase99Bundle,
    build_test_freeze_contract,
    freeze_phase9_9_artifacts,
    load_phase9_9_bundle,
)
from tradingbot.ml.paper_trading.shadow_engine import ShadowEngine, ShadowResult

__all__ = [
    "Phase99Bundle",
    "ShadowEngine",
    "ShadowResult",
    "build_test_freeze_contract",
    "freeze_phase9_9_artifacts",
    "load_phase9_9_bundle",
]
