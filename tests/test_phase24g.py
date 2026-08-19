"""Phase 24G — optimized build_unified_frame validation tests."""

from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24g"

VERDICTS = {"SAFE_DEPLOYED", "ROLLBACK_REQUIRED", "NO_MEANINGFUL_IMPROVEMENT"}


class TestUnifiedFrameBitParity(unittest.TestCase):
    def test_legacy_equals_optimized_over_sliding_window(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
        from tradingbot.ml.research.phase13_9.unified_features import (
            _build_unified_frame_legacy,
            _build_unified_frame_optimized,
        )
        from tradingbot.ml.research.regime_router.phase99_feature_validation import (
            normalize_candles_for_builder,
        )

        base_dir = load_legacy_config().get("BASE_DIR")
        candles = CandleStore(base_dir).load("XAUUSD", "M5")
        dataset = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
        if candles is None or dataset is None:
            self.skipTest("market data missing")

        norm = normalize_candles_for_builder(prepare_calibration_candles(candles, days=180))
        warmup = 250
        for bar_index in range(warmup, min(warmup + 30, len(norm))):
            chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
            legacy = _build_unified_frame_legacy(chunk, dataset)
            optimized = _build_unified_frame_optimized(chunk, dataset)
            pd.testing.assert_frame_equal(
                legacy.reset_index(drop=True),
                optimized.reset_index(drop=True),
                check_exact=True,
                check_dtype=True,
            )


class TestUnifiedFrameRollback(unittest.TestCase):
    def test_env_false_matches_legacy(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
        from tradingbot.ml.research.phase13_9.unified_features import (
            ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME,
            _build_unified_frame_legacy,
            build_unified_frame,
        )
        from tradingbot.ml.research.regime_router.phase99_feature_validation import (
            normalize_candles_for_builder,
        )

        base_dir = load_legacy_config().get("BASE_DIR")
        candles = CandleStore(base_dir).load("XAUUSD", "M5")
        dataset = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
        if candles is None or dataset is None:
            self.skipTest("market data missing")

        norm = normalize_candles_for_builder(prepare_calibration_candles(candles, days=90))
        chunk = norm.iloc[max(0, 300 - 300) : 300]

        os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "false"
        rolled_back = build_unified_frame(chunk, dataset)
        legacy = _build_unified_frame_legacy(chunk, dataset)
        os.environ[ENV_ENABLE_OPTIMIZED_UNIFIED_FRAME] = "true"

        pd.testing.assert_frame_equal(
            legacy.reset_index(drop=True),
            rolled_back.reset_index(drop=True),
            check_exact=True,
        )


class TestUnifiedFrameLatency(unittest.TestCase):
    def test_optimized_not_slower_than_legacy(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
        from tradingbot.ml.research.phase13_9.unified_features import (
            _build_unified_frame_legacy,
            _build_unified_frame_optimized,
        )
        from tradingbot.ml.research.regime_router.phase99_feature_validation import (
            normalize_candles_for_builder,
        )

        base_dir = load_legacy_config().get("BASE_DIR")
        candles = CandleStore(base_dir).load("XAUUSD", "M5")
        dataset = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
        if candles is None or dataset is None:
            self.skipTest("market data missing")

        norm = normalize_candles_for_builder(prepare_calibration_candles(candles, days=90))
        chunk = norm.iloc[max(0, 300 - 300) : 300]

        legacy_times: list[float] = []
        opt_times: list[float] = []
        for _ in range(10):
            t0 = time.perf_counter()
            _build_unified_frame_legacy(chunk, dataset)
            legacy_times.append((time.perf_counter() - t0) * 1000)
        for _ in range(10):
            t0 = time.perf_counter()
            _build_unified_frame_optimized(chunk, dataset)
            opt_times.append((time.perf_counter() - t0) * 1000)

        self.assertLessEqual(sum(opt_times) / len(opt_times), sum(legacy_times) / len(legacy_times))


class TestPhase24GDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        final_path = PHASE_DIR / "phase24g_final_report.json"
        if not final_path.is_file():
            from tradingbot.ml.research.phase24g.run_validation import write_deliverables

            cls.result = write_deliverables(quick=True)
        else:
            cls.result = {"verdict": json.loads(final_path.read_text(encoding="utf-8"))["verdict"]}

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result.get("verdict"), VERDICTS)

    def test_feature_parity_all_pass(self) -> None:
        payload = json.loads((PHASE_DIR / "feature_parity.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["all_pass"])

    def test_prediction_parity(self) -> None:
        payload = json.loads((PHASE_DIR / "prediction_parity.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["all_match"])

    def test_rollback_validation(self) -> None:
        payload = json.loads((PHASE_DIR / "rollback_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["rollback_matches_legacy"])


if __name__ == "__main__":
    unittest.main()
