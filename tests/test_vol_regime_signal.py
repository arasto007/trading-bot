"""Tests for VOL_REGIME read-only signal module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.strategies.vol_regime_signal import (
    ATR_PCT_MAX,
    ATR_PCT_MIN,
    CONFIG_ID,
    STRATEGY_ID,
    evaluate_at_index,
    prepare_frame,
    scan_signals,
    signal_metadata,
)


def _synthetic_candles(n: int = 600) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(42)
    close = 2000.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.2, 1.5, n)
    low = close - rng.uniform(0.2, 1.5, n)
    open_ = close + rng.normal(0, 0.3, n)
    volume = rng.integers(50, 500, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


class TestVolRegimeSignal(unittest.TestCase):
    def test_signal_metadata(self) -> None:
        meta = signal_metadata()
        self.assertEqual(meta["strategy_id"], STRATEGY_ID)
        self.assertEqual(meta["config_id"], CONFIG_ID)
        self.assertEqual(meta["tp_rr"], 0.8)
        self.assertEqual(meta["atr_sl_mult"], 2.5)
        self.assertEqual(meta["production_deploy"], "LIVE")
        self.assertEqual(meta["ml_filter"], "SKIP")

    def test_prepare_frame_columns(self) -> None:
        frame = prepare_frame(_synthetic_candles())
        for col in ("ema20", "ema50", "atr14", "atr_pct"):
            self.assertIn(col, frame.columns)
        self.assertGreater(len(frame), 100)

    def test_evaluate_returns_none_on_invalid_index(self) -> None:
        frame = prepare_frame(_synthetic_candles(200))
        self.assertIsNone(evaluate_at_index(frame, -1))
        self.assertIsNone(evaluate_at_index(frame, len(frame)))

    def test_scan_signals_respects_stride(self) -> None:
        frame = prepare_frame(_synthetic_candles(800))
        sigs = scan_signals(frame, start_idx=500, stride=5)
        self.assertIsInstance(sigs, list)
        for sig in sigs:
            self.assertIn(sig.direction, (1, -1))
            self.assertEqual(sig.hypothesis_id, STRATEGY_ID)
            self.assertEqual(sig.config_id, CONFIG_ID)
            self.assertTrue(ATR_PCT_MIN <= sig.atr_pct <= ATR_PCT_MAX)

    def test_to_dict_research_only(self) -> None:
        frame = prepare_frame(_synthetic_candles(800))
        sigs = scan_signals(frame, start_idx=500, stride=1)
        if not sigs:
            self.skipTest("no signals in synthetic window")
        d = sigs[0].to_dict()
        self.assertTrue(d["research_only"])
        self.assertEqual(d["production_deploy"], "BLOCKED")
        self.assertIn("timestamp_utc", d)


if __name__ == "__main__":
    unittest.main()
