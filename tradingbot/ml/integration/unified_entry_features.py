"""ML Kernel entry-feature bridge — delegates to UnifiedFeatureStore (Phase D1)."""

from __future__ import annotations

from typing import Any

from tradingbot.domain.models import TradingSignal
from tradingbot.ml.features.unified_feature_store import UnifiedFeatureStore, build_live

__all__ = ["UnifiedFeatureStore", "build_live", "build_ml_kernel_entry_features"]


def build_ml_kernel_entry_features(
    signal: TradingSignal,
    snapshot: dict[str, Any],
    regime: str,
    *,
    spread_pips: float = 0.0,
) -> dict[str, float]:
    return UnifiedFeatureStore.build_for_ml_kernel(
        signal,
        snapshot,
        regime,
        spread_pips=spread_pips,
    )
