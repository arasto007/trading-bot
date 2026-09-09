"""Phase 64 strategy event forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase64_strategy_event_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE64_JSON,
    PHASE64_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase64_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE64_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase64_collection(root)


class TestPhase64(unittest.TestCase):
    def test_stop_out_and_outlier_diagnosis(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE64_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["lineage_meta"]["resolved_event_count"], 419)
        self.assertEqual(payload["lineage_meta"]["event_count"], 420)
        self.assertFalse(payload["lineage_meta"]["strategy_rerun"])
        self.assertGreater(payload["stop_out_anatomy"]["LOSS_SL"], payload["stop_out_anatomy"]["WIN_TP"])
        self.assertEqual(payload["stop_out_anatomy"]["spread_claim"], "NOT_SUPPORTED")
        self.assertGreater(payload["mae_mfe"]["losers_mfe_gt_0_5R"], 0)
        self.assertTrue(payload["mae_mfe"]["sl_tp_not_changed"])
        self.assertIn("2026-01-21", str(payload["outlier"]["event"]["timestamp"]))
        self.assertAlmostEqual(float(payload["outlier"]["event"]["r_result"]), 31.8367, places=2)
        self.assertFalse(payload["outlier"]["representative_strategy_behavior"])
        self.assertLess(payload["counterfactual"]["remove_top_1"]["expectancy_R"], 0)
        self.assertEqual(payload["causes"]["PRIMARY"], "EXIT_PROBLEM")
        self.assertEqual(payload["folds"]["OOS"]["oos_positive_because"], "B_few_extreme_winners")
        self.assertFalse(payload["entry_quality"]["optimized"])
        self.assertEqual(payload["density"]["SIGNAL_DUPLICATION"], "HIGHLY_DUPLICATED")

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE64_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase64_strategy_event_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertEqual(payload["production_safety"]["SL_TP"], "NOT_CHANGED")
        self.assertIn("LOSS_SL", (root / PHASE64_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
