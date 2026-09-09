"""Phase 65 diagnostic experiment tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase64_strategy_event_forensics import PHASE64_JSON, run_phase64_collection
from tradingbot.backtest.phase65_diagnostic_experiments import (
    PHASE,
    PHASE65_JSON,
    PHASE65_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase65_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE64_JSON).is_file():
        run_phase64_collection(root)
    art = root / PHASE65_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("thresholds_searched") is False:
            return
    run_phase65_collection(root)


class TestPhase65(unittest.TestCase):
    def test_predeclared_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE65_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["thresholds_searched"])
        self.assertFalse(payload["parameters_optimized"])
        ex = payload["experiments"]
        self.assertIn("A_duplicate_removal", ex)
        self.assertIn("B_outlier_robustness", ex)
        self.assertFalse(ex["A_duplicate_removal"]["production_logic_changed"])
        self.assertFalse(ex["B_outlier_robustness"]["positive_expectancy_survives_top1_removed"])
        self.assertFalse(ex["F_cost"]["new_broker_costs_invented"])
        self.assertFalse(ex["E_recency"]["split_points_optimized"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE65_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase65_diagnostic_experiments.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("No threshold search", (root / PHASE65_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
