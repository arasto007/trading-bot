"""Phase 13.6 — cached research engines (avoid repeated ML retraining)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.research.regime_router.trend_engine_adapter import TrendEngineAdapter


@dataclass
class EngineCache:
    candles: pd.DataFrame
    symbol: str = "XAUUSD"
    seed: int = 42
    base_dir: str | None = None
    _range: RangeEngineAdapter | None = field(default=None, init=False, repr=False)
    _trend: dict[float, TrendEngineAdapter] = field(default_factory=dict, init=False, repr=False)

    def range_engine(self) -> RangeEngineAdapter:
        if self._range is None:
            self._range = RangeEngineAdapter.load(symbol=self.symbol, base_dir=self.base_dir)
        return self._range

    def trend_engine(self, threshold: float) -> TrendEngineAdapter:
        key = round(float(threshold), 4)
        if key not in self._trend:
            adapter = TrendEngineAdapter.load(
                self.candles,
                symbol=self.symbol,
                base_dir=self.base_dir,
                seed=self.seed,
                threshold=key,
            )
            self._trend[key] = adapter
        return self._trend[key]
