"""Tests for adaptive multi-regime strategy registry."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.adaptive_regime_strategy_registry import (
    AdaptiveRegimeStrategyRegistry,
)
from tradingbot.domain.models import MarketKey
from tradingbot.strategies.adaptive_regime import (
    classify_regime,
    evaluate_adaptive_at_index,
    prepare_adaptive_frame,
)


def _synthetic_candles(n: int = 900, *, trend: float = 0.3) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(11)
    close = 2400.0 + np.cumsum(rng.normal(trend, 0.8, n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    open_ = close + rng.normal(0, 0.4, n)
    volume = rng.integers(80, 800, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


class TestAdaptiveRegime(unittest.TestCase):
    def test_classify_regime_returns_known_label(self) -> None:
        frame = prepare_adaptive_frame(_synthetic_candles())
        row = frame.iloc[-1]
        regime = classify_regime(row)
        self.assertIn(regime, ("TREND", "RANGE", "HIGH_VOLATILITY", "LOW_VOLATILITY", "NO_TRADE"))

    def test_evaluate_does_not_crash(self) -> None:
        frame = prepare_adaptive_frame(_synthetic_candles())
        sig = evaluate_adaptive_at_index(frame, len(frame) - 1)
        if sig is not None:
            self.assertIn(sig.direction, (1, -1))
            self.assertTrue(sig.strategy_id)

    def test_m5_kernel_not_rejected(self) -> None:
        reg = AdaptiveRegimeStrategyRegistry()
        frame = prepare_adaptive_frame(_synthetic_candles())
        self.assertIsNone(reg.generate_signal(MarketKey("EURUSD", "M5"), frame))
        reg.generate_signal(MarketKey("XAUUSD", "M5"), frame)
        self.assertIsNone(reg.generate_signal(MarketKey("XAUUSD", "H1"), frame))


if __name__ == "__main__":
    unittest.main()
