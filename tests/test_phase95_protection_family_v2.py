"""Phase 95 protection family v2 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase90_profit_giveback_path_forensics import PHASE90_JSON, run_phase90_collection
from tradingbot.backtest.phase91_reversal_timing_forensics import PHASE91_JSON, run_phase91_collection
from tradingbot.backtest.phase92_mfe_mae_conditional_forensics import PHASE92_JSON, run_phase92_collection
from tradingbot.backtest.phase93_tail_preservation_forensics import PHASE93_JSON, run_phase93_collection
from tradingbot.backtest.phase95_protection_family_v2 import (
    FAMILIES,
    PHASE,
    PHASE40_JSON,
    PHASE95_JSON,
    PHASE95_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase95_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
ALLOWED = {"HELPFUL", "NEUTRAL", "HARMFUL", "DATA_LIMITED"}


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE90_JSON).is_file():
        run_phase90_collection(root)
    if not (root / PHASE91_JSON).is_file():
        run_phase91_collection(root)
    if not (root / PHASE92_JSON).is_file():
        run_phase92_collection(root)
    if not (root / PHASE93_JSON).is_file():
        run_phase93_collection(root)
    art = root / PHASE95_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("n_families") == 4:
            return
    run_phase95_collection(root)


class TestPhase95(unittest.TestCase):
    def test_four_predeclared_families(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE95_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["n_families"], 4)
        self.assertTrue(payload["rules_declared_before_walks"])
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["oos_used_for_selection"])
        for name in FAMILIES:
            self.assertIn(name, payload["rules"])
            self.assertIn(payload["counterfactuals"][name]["status"], ALLOWED)
            self.assertIn("activation", payload["rules"][name])
            self.assertIn("TRAIN", payload["counterfactuals"][name])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE95_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase95_protection_family_v2.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("THEORETICAL", (root / PHASE95_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
