"""Phase 27C — prediction cache key fix tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.ml.integration.pipeline_cache import (
    PipelineCache,
    resolve_closed_candle_timestamp,
    unified_row_fingerprint,
)

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27c"

DELIVERABLES = [
    "cache_key_before.json",
    "cache_key_after.json",
    "cache_collision_report.json",
    "cache_statistics.json",
    "prediction_uniqueness.json",
    "performance_comparison.json",
    "final_report.json",
]


class TestPredictionCacheKey(unittest.TestCase):
    def setUp(self) -> None:
        PipelineCache.reset()

    def _sample_candles(self, n: int = 100) -> pd.DataFrame:
        idx = pd.date_range("2026-06-01", periods=n, freq="5min", tz="UTC")
        return pd.DataFrame(
            {
                "open": range(n),
                "high": range(n),
                "low": range(n),
                "close": range(n),
                "volume": [1.0] * n,
            },
            index=idx,
        )

    def test_closed_candle_timestamp_is_iso_not_integer(self) -> None:
        candles = self._sample_candles(80)
        ts = resolve_closed_candle_timestamp(candles)
        self.assertIn("T", ts)
        self.assertNotIn(ts, {"79", "78", "0"})

    def test_prediction_keys_unique_per_candle(self) -> None:
        candles = self._sample_candles(120)
        row_a = pd.Series({"rsi": 45.0, "adx": 20.0})
        row_b = pd.Series({"rsi": 55.0, "adx": 30.0})
        keys = set()
        for i in range(60, 110):
            slice_df = candles.iloc[: i + 1]
            row = row_a if i % 2 == 0 else row_b
            key = PipelineCache.build_prediction_cache_key(
                symbol="XAUUSD",
                timeframe="M5",
                candles=slice_df,
                unified_row=row,
                base_dir=".",
            )
            self.assertNotIn("|79|", key)
            self.assertIn("2026-", key)
            keys.add(key)
        self.assertEqual(len(keys), 50)

    def test_same_candle_same_key(self) -> None:
        candles = self._sample_candles(80)
        row = pd.Series({"rsi": 50.0, "adx": 25.0})
        k1 = PipelineCache.build_prediction_cache_key(
            symbol="XAUUSD",
            timeframe="M5",
            candles=candles,
            unified_row=row,
            base_dir=".",
        )
        k2 = PipelineCache.build_prediction_cache_key(
            symbol="XAUUSD",
            timeframe="M5",
            candles=candles,
            unified_row=row,
            base_dir=".",
        )
        self.assertEqual(k1, k2)

    def test_cache_roundtrip(self) -> None:
        key = "XAUUSD:M5:2026-06-01T00:00:00+00:00:abc:model"
        PipelineCache.set_prediction(key, "chk1", {"direction": "BUY"})
        cached = PipelineCache.get_prediction(key)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["direction"], "BUY")


class TestPhase27CDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report.get("verdict"), "CACHE_FIXED")

    def test_zero_collisions(self) -> None:
        collision = json.loads(
            (PHASE_DIR / "cache_collision_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(collision.get("cache_collisions"), 0)
        self.assertTrue(collision.get("pass"))

    def test_prediction_uniqueness(self) -> None:
        uniq = json.loads(
            (PHASE_DIR / "prediction_uniqueness.json").read_text(encoding="utf-8")
        )
        self.assertEqual(uniq.get("prediction_uniqueness_pct"), 100.0)
        self.assertGreaterEqual(uniq.get("bars_evaluated", 0), 1000)


if __name__ == "__main__":
    unittest.main()
