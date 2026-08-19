"""Phase 24F — incremental unified frame parity tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24f"

VERDICTS = {"SAFE_INCREMENTAL_REBUILD", "PARTIAL_INCREMENTAL_ONLY", "UNSAFE_TO_IMPLEMENT"}


class TestIncrementalFrameParity(unittest.TestCase):
    def test_cold_start_incremental_matches_production_each_bar(self) -> None:
        """Each bar compared independently (state=None) must match full rebuild."""
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
        from tradingbot.ml.research.phase24f.incremental_frame import (
            incremental_unified_frame_step,
            production_unified_frame,
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
        warmup = 250
        for bar_index in range(warmup, min(warmup + 20, len(norm))):
            chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
            full = production_unified_frame(chunk, dataset)
            inc, _ = incremental_unified_frame_step(chunk, dataset, None)
            pd.testing.assert_frame_equal(
                full.reset_index(drop=True),
                inc.reset_index(drop=True),
                check_exact=True,
            )

    def test_row_reuse_fails_after_stable_300_window(self) -> None:
        """Proves proposed row-reuse breaks parity once tail(300) is stable."""
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
        from tradingbot.ml.research.phase24f.incremental_frame import (
            incremental_unified_frame_step,
            production_unified_frame,
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
        state = None
        mismatch_at = None
        for bar_index in range(250, 305):
            chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
            full = production_unified_frame(chunk, dataset)
            inc, state = incremental_unified_frame_step(chunk, dataset, state)
            if not full.reset_index(drop=True).equals(inc.reset_index(drop=True)):
                mismatch_at = bar_index
                break

        self.assertIsNotNone(mismatch_at, "expected row-reuse parity failure")
        self.assertGreaterEqual(mismatch_at, 300)


class TestPhase24FDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        final_path = PHASE_DIR / "phase24f_final_report.json"
        if not final_path.is_file():
            from tradingbot.ml.research.phase24f.run_investigation import write_deliverables

            cls.result = write_deliverables(quick=False)
        else:
            cls.result = json.loads(final_path.read_text(encoding="utf-8"))
            cls.result = {"verdict": cls.result.get("verdict")}

    def test_verdict_unsafe(self) -> None:
        self.assertEqual(self.result.get("verdict"), "UNSAFE_TO_IMPLEMENT")

    def test_overlap_drift_documented(self) -> None:
        payload = json.loads((PHASE_DIR / "feature_parity_proof.json").read_text(encoding="utf-8"))
        drift = payload["consecutive_full_rebuild_overlap"]
        self.assertFalse(drift["overlap_stable_between_consecutive_full_rebuilds"])
        self.assertGreater(len(drift["failures"]), 0)

    def test_feature_parity_incremental_fails_with_row_reuse(self) -> None:
        payload = json.loads((PHASE_DIR / "feature_parity_proof.json").read_text(encoding="utf-8"))
        self.assertFalse(payload["all_pass"])
        for key in ("100", "500", "1000"):
            self.assertIn(key, payload["bar_count_results"])

    def test_deliverables_exist(self) -> None:
        for name in (
            "dependency_graph.json",
            "column_dependency.json",
            "incremental_algorithm.json",
            "feature_parity_proof.json",
            "prediction_parity.json",
            "latency_projection.json",
            "risk_analysis.json",
            "rollback_plan.json",
            "phase24f_final_report.json",
        ):
            self.assertTrue((PHASE_DIR / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
