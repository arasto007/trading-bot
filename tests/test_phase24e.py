"""Phase 24E — dataset_v2 memory cache tests."""

from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24e"

VERDICTS = {"SAFE_DEPLOYED", "ROLLBACK_REQUIRED", "NO_LATENCY_IMPROVEMENT"}


class TestDatasetMemoryCache(unittest.TestCase):
    def setUp(self) -> None:
        from tradingbot.ml.dataset.memory_cache import DatasetMemoryCache

        DatasetMemoryCache.reset()

    def test_cache_enabled_by_default(self) -> None:
        from tradingbot.ml.dataset.memory_cache import dataset_memory_cache_enabled

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENABLE_DATASET_MEMORY_CACHE", None)
            self.assertTrue(dataset_memory_cache_enabled())

    def test_load_v2_uses_cache_on_second_call(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.dataset.memory_cache import DatasetMemoryCache
        from tradingbot.ml.dataset.store import DatasetStore

        base_dir = load_legacy_config().get("BASE_DIR")
        store = DatasetStore(base_dir)
        first = store.load_v2("XAUUSD", "M5")
        if first is None:
            self.skipTest("dataset_v2 not available")
        second = store.load_v2("XAUUSD", "M5")
        stats = DatasetMemoryCache.stats()
        self.assertIsNotNone(second)
        self.assertEqual(stats["loads_from_disk"], 1)
        self.assertGreaterEqual(stats["loads_from_memory"], 1)

    def test_rollback_bypasses_cache(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.dataset.memory_cache import (
            ENV_ENABLE_DATASET_MEMORY_CACHE,
            DatasetMemoryCache,
        )
        from tradingbot.ml.dataset.store import DatasetStore

        base_dir = load_legacy_config().get("BASE_DIR")
        with mock.patch.dict(os.environ, {ENV_ENABLE_DATASET_MEMORY_CACHE: "false"}, clear=False):
            DatasetMemoryCache.reset()
            store = DatasetStore(base_dir)
            df = store.load_v2("XAUUSD", "M5")
            if df is None:
                self.skipTest("dataset_v2 not available")
            store.load_v2("XAUUSD", "M5")
            stats = DatasetMemoryCache.stats()
            self.assertEqual(stats["loads_from_memory"], 0)

    def test_unified_frame_parity(self) -> None:
        import pandas as pd
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.memory_cache import (
            ENV_ENABLE_DATASET_MEMORY_CACHE,
            DatasetMemoryCache,
        )
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
        from tradingbot.ml.research.regime_router.phase99_feature_validation import (
            normalize_candles_for_builder,
        )

        base_dir = load_legacy_config().get("BASE_DIR")
        candles = CandleStore(base_dir).load("XAUUSD", "M5")
        if candles is None or candles.empty:
            self.skipTest("candles missing")
        chunk = normalize_candles_for_builder(candles).tail(300)

        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "false"
        ds_off = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
        uf_off = build_unified_frame(chunk, ds_off)

        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
        DatasetMemoryCache.reset()
        ds_on = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
        uf_on = build_unified_frame(chunk, ds_on)

        if uf_off.empty or uf_on.empty:
            self.skipTest("unified frame empty")
        pd.testing.assert_frame_equal(uf_off.reset_index(drop=True), uf_on.reset_index(drop=True))

    def test_latency_improvement_on_repeated_loads(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.dataset.memory_cache import (
            ENV_ENABLE_DATASET_MEMORY_CACHE,
            DatasetMemoryCache,
        )
        from tradingbot.ml.dataset.store import DatasetStore

        base_dir = load_legacy_config().get("BASE_DIR")
        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
        DatasetMemoryCache.reset()
        store = DatasetStore(base_dir)
        if store.load_v2("XAUUSD", "M5") is None:
            self.skipTest("dataset_v2 not available")
        t0 = time.perf_counter()
        for _ in range(30):
            store.load_v2("XAUUSD", "M5")
        cached_ms = (time.perf_counter() - t0) * 1000

        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "false"
        t0 = time.perf_counter()
        for _ in range(30):
            DatasetStore(base_dir).load_v2("XAUUSD", "M5")
        direct_ms = (time.perf_counter() - t0) * 1000

        self.assertLess(cached_ms, direct_ms * 0.5)


class TestPhase24EDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.ml.research.phase24e.run_validation import write_deliverables

        cls.result = write_deliverables(quick=True)

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result.get("verdict"), VERDICTS)

    def test_deliverables_exist(self) -> None:
        for name in (
            "implementation_report.json",
            "latency_before_after.json",
            "feature_parity.json",
            "phase24e_final_report.json",
        ):
            self.assertTrue((PHASE_DIR / name).is_file(), name)

    def test_feature_parity_passes(self) -> None:
        payload = json.loads((PHASE_DIR / "feature_parity.json").read_text(encoding="utf-8"))
        self.assertTrue(payload.get("all_frames_equal", payload.get("all_column_hashes_match")))
        self.assertTrue(payload["fingerprints_match"])


if __name__ == "__main__":
    unittest.main()
