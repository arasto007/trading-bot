"""Phase 24I — unified feature input tests."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24i"

VERDICTS = {"SAFE_DEPLOYED", "ROLLBACK_REQUIRED", "PARITY_FAILED"}


class TestUnifiedFeatureInput(unittest.TestCase):
    def test_legacy_path_uses_feature_builder(self) -> None:
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
        from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
        from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
        from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
        from tradingbot.ml.research.regime_router.unified_feature_input import ENV_ENABLE_UNIFIED_FEATURE_INPUT

        candles = CandleStore(None).load("XAUUSD", "M5")
        dataset = DatasetStore(None).load_v2("XAUUSD", "M5")
        if candles is None or dataset is None:
            self.skipTest("market data missing")

        norm = normalize_candles_for_builder(candles)
        ds_max = dataset["timestamp"].max()
        idx = int(norm.index.get_indexer([ds_max], method="nearest")[0])
        chunk = norm.iloc[max(0, idx + 1 - 300) : idx + 1]
        row = attach_top5_features(build_unified_frame(chunk, dataset)).iloc[-1]
        adapter = RangeEngineAdapter.load(symbol="XAUUSD")

        os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "false"
        result = adapter.evaluate(row=row, candles=chunk, bar_index=len(chunk) - 1)
        self.assertEqual(result.get("feature_source"), "feature_builder")

    def test_parity_legacy_vs_unified_with_verify(self) -> None:
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
        from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
        from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
        from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
        from tradingbot.ml.research.regime_router.unified_feature_input import (
            ENV_ENABLE_UNIFIED_BUILDER_VERIFY,
            ENV_ENABLE_UNIFIED_FEATURE_INPUT,
        )

        candles = CandleStore(None).load("XAUUSD", "M5")
        dataset = DatasetStore(None).load_v2("XAUUSD", "M5")
        if candles is None or dataset is None:
            self.skipTest("market data missing")

        norm = normalize_candles_for_builder(candles)
        idx = int(norm.index.get_indexer([dataset["timestamp"].max()], method="nearest")[0])
        adapter = RangeEngineAdapter.load(symbol="XAUUSD")

        os.environ[ENV_ENABLE_UNIFIED_BUILDER_VERIFY] = "true"
        for bi in range(max(250, idx - 30), min(idx + 30, len(norm))):
            chunk = norm.iloc[max(0, bi + 1 - 300) : bi + 1]
            row = attach_top5_features(build_unified_frame(chunk, dataset)).iloc[-1]
            bi_idx = len(chunk) - 1
            os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "false"
            old = adapter.evaluate(row=row, candles=chunk, bar_index=bi_idx)
            os.environ[ENV_ENABLE_UNIFIED_FEATURE_INPUT] = "true"
            new = adapter.evaluate(row=row, candles=chunk, bar_index=bi_idx)
            self.assertEqual(old.get("signal"), new.get("signal"))
            self.assertEqual(old.get("probability"), new.get("probability"))


class TestPhase24IDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        final_path = PHASE_DIR / "phase24i_final_report.json"
        if not final_path.is_file():
            from tradingbot.ml.research.phase24i.run_validation import write_deliverables

            cls.result = write_deliverables(quick=True)
        else:
            cls.result = {"verdict": json.loads(final_path.read_text(encoding="utf-8"))["verdict"]}

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result.get("verdict"), VERDICTS)

    def test_parity_pass(self) -> None:
        payload = json.loads((PHASE_DIR / "parity_report.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["all_pass"])

    def test_rollback(self) -> None:
        payload = json.loads((PHASE_DIR / "rollback_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["rollback_matches_legacy"])

    def test_deliverables_exist(self) -> None:
        for name in (
            "feature_source_selection.json",
            "phase24i_final_report.json",
        ):
            self.assertTrue((PHASE_DIR / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
