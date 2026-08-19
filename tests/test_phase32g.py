"""Phase 32G — safe runtime cache optimization tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERDICTS = {"SAFE_OPTIMIZATION_SUCCESS", "SAFE_OPTIMIZATION_FAILED", "PARITY_BROKEN", "ROLLBACK_REQUIRED"}


class TestPhase32GCache(unittest.TestCase):
    def setUp(self) -> None:
        from tradingbot.ml.dataset.memory_cache import DatasetMemoryCache
        from tradingbot.ml.integration.pipeline_cache import PipelineCache

        PipelineCache.reset()
        DatasetMemoryCache.reset()

    def test_multi_slot_cache_preserves_per_timeframe(self) -> None:
        import pandas as pd
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.integration.pipeline_cache import PipelineCache, unified_frame_sha256
        from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

        base_dir = load_legacy_config().get("BASE_DIR")
        symbol = "XAUUSD"
        frames: dict[str, str] = {}
        for tf in ("M5", "M15", "H4"):
            raw = CandleStore(base_dir).load(symbol, tf)
            if raw is None or raw.empty:
                self.skipTest(f"missing candles {tf}")
            chunk = normalize_candles_for_builder(raw).tail(300)
            uf = PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
            frames[tf] = unified_frame_sha256(uf)

        stats = PipelineCache.cache_stats()
        self.assertGreaterEqual(stats["feature_cache_slots"], 3)
        for tf in ("M5", "M15", "H4"):
            raw = CandleStore(base_dir).load(symbol, tf)
            chunk = normalize_candles_for_builder(raw).tail(300)
            uf2 = PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
            self.assertEqual(frames[tf], unified_frame_sha256(uf2))

        stats2 = PipelineCache.cache_stats()
        self.assertGreater(stats2["feature_cache_hits"], 0)

    def test_market_context_cache_hit(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.decision_engine.validation import build_market_context
        from tradingbot.ml.integration.factory import build_kernel_adapter
        from tradingbot.ml.integration.pipeline_cache import PipelineCache
        from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

        base_dir = load_legacy_config().get("BASE_DIR")
        symbol, tf = "XAUUSD", "M5"
        raw = CandleStore(base_dir).load(symbol, tf)
        if raw is None or raw.empty:
            self.skipTest("missing candles")
        chunk = normalize_candles_for_builder(raw).tail(300)
        adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, enable_monitoring=False)
        range_inner, trend_inner = adapter._engine_inners()
        unified = PipelineCache.get_unified_frame(chunk, base_dir=base_dir, symbol=symbol, timeframe=tf)
        row = unified.iloc[-1]
        direct = build_market_context(
            row,
            symbol=symbol,
            timeframe=tf,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=chunk,
            bar_index=len(chunk) - 1,
        )
        cached = PipelineCache.get_market_context(
            row,
            symbol=symbol,
            timeframe=tf,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=chunk,
            bar_index=len(chunk) - 1,
            base_dir=base_dir,
        )
        cached2 = PipelineCache.get_market_context(
            row,
            symbol=symbol,
            timeframe=tf,
            range_engine=range_inner,
            trend_engine=trend_inner,
            candles=chunk,
            bar_index=len(chunk) - 1,
            base_dir=base_dir,
        )
        self.assertEqual(direct.to_dict(), cached.to_dict())
        self.assertEqual(cached.to_dict(), cached2.to_dict())
        stats = PipelineCache.cache_stats()
        self.assertGreaterEqual(stats["market_context_cache_hits"], 1)

    def test_startup_warm_loads_dataset_once(self) -> None:
        import os
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.dataset.memory_cache import (
            ENV_ENABLE_DATASET_MEMORY_CACHE,
            DatasetMemoryCache,
        )
        from tradingbot.ml.integration.pipeline_cache import PipelineCache

        base_dir = load_legacy_config().get("BASE_DIR")
        os.environ[ENV_ENABLE_DATASET_MEMORY_CACHE] = "true"
        DatasetMemoryCache.reset()
        result = PipelineCache.warm_datasets(base_dir=base_dir)
        if not result.get("warmed"):
            self.skipTest("no datasets to warm")
        stats = DatasetMemoryCache.stats()
        self.assertGreaterEqual(stats["loads_from_disk"] + stats["loads_from_memory"], 1)
        self.assertGreaterEqual(len(result["warmed"]), 1)
        self.assertEqual(stats["loads_from_memory"], 0)


class TestPhase32GDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.ml.research.phase32g.run_validation import run_validation

        cls.result = run_validation(quick=True)

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result.get("verdict"), VERDICTS)

    def test_deliverables_exist(self) -> None:
        for name in (
            "safe_cache_design.json",
            "before_after_latency.json",
            "cache_statistics.json",
            "startup_warm_results.json",
            "feature_parity.json",
            "signal_parity.json",
            "probability_parity.json",
            "trade_parity.json",
            "memory_usage.json",
            "performance_gain.json",
            "phase32g_final_report.json",
        ):
            self.assertTrue((PROJECT_ROOT / name).is_file(), name)

    def test_feature_parity_passes(self) -> None:
        payload = json.loads((PROJECT_ROOT / "feature_parity.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["all_match"])

    def test_signal_parity_passes(self) -> None:
        payload = json.loads((PROJECT_ROOT / "signal_parity.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["all_match"])


if __name__ == "__main__":
    unittest.main()
