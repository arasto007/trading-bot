"""Phase 22C — runtime threshold overrides (frozen artifacts unchanged)."""

from __future__ import annotations

from tradingbot.ml.paper_trading.signal_engine import SignalConfig, SignalEngine
from tradingbot.ml.phase15a.config import RANGE_ENGINE_ID
from tradingbot.ml.research.phase22c.config import Phase22CConfig


def apply_phase22c_range_thresholds(registry, cfg: Phase22CConfig) -> None:
    """Symmetric range thresholds — fixes SELL-only bias from asymmetric 0.55/0.45 + low prob skew."""
    if not cfg.enabled:
        return
    if cfg.range_sell_threshold >= cfg.range_buy_threshold:
        raise ValueError("PHASE22C_RANGE_SELL_THRESHOLD must be < PHASE22C_RANGE_BUY_THRESHOLD")
    wrapped = registry.get(RANGE_ENGINE_ID)
    if wrapped is None:
        return
    inner = getattr(wrapped, "inner", None)
    if inner is None:
        return
    range_adapter = getattr(inner, "_inner", inner)
    if not hasattr(range_adapter, "signal_engine"):
        return
    range_adapter.signal_engine = SignalEngine(
        SignalConfig(
            buy_threshold=cfg.range_buy_threshold,
            sell_threshold=cfg.range_sell_threshold,
        )
    )
