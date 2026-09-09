"""Phase 68 exit forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase68_exit_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE68_JSON,
    PHASE68_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase68_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE68_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase68_collection(root)


class TestPhase68(unittest.TestCase):
    def test_exit_path_and_cohorts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE68_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["lineage_meta"]["resolved_event_count"], 419)
        self.assertEqual(payload["lineage_meta"]["LOSS_SL"], 298)
        self.assertEqual(payload["lineage_meta"]["WIN_TP"], 121)
        self.assertFalse(payload["strategy_rerun"])
        self.assertFalse(payload["event_tape_altered"])
        self.assertGreaterEqual(payload["lineage_meta"]["path_walked"], 400)
        self.assertGreater(payload["LOSS_AFTER_0_5R"], 100)
        self.assertGreater(payload["LOSS_AFTER_1R"], 50)
        self.assertIn("LOSS_AFTER_0.5R", payload["cohorts"])
        self.assertTrue(payload["outlier_kept_in_baseline"]["official_baseline_includes_top1"])
        self.assertIn("2026-01-21", str(payload["outlier_kept_in_baseline"]["timestamp"]))
        self.assertLess(payload["TOP1_REMOVAL_EXPECTANCY"], 0)
        self.assertEqual(payload["mechanism_ranking"]["PRIMARY_MECHANISM"], "C_PROFIT_PROTECTION")

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE68_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase68_exit_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertEqual(payload["production_safety"]["SL_TP"], "NOT_CHANGED")
        self.assertIn("PRIMARY_MECHANISM", (root / PHASE68_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
