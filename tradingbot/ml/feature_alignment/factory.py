"""Phase 16A — distribution aligner factory (dependency injection)."""

from __future__ import annotations

from functools import lru_cache

from tradingbot.ml.feature_alignment.distribution_aligner import DistributionAligner


@lru_cache(maxsize=4)
def build_distribution_aligner(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
) -> DistributionAligner:
    key = base_dir or ""
    return DistributionAligner.build(base_dir=key or None, symbol=symbol, timeframe=timeframe)
