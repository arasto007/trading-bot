"""Phase 62 operator-action economics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase61_edge_survival_forensics import PHASE61_JSON, run_phase61_collection
from tradingbot.backtest.phase62_operator_action_economics import (
    PHASE,
    PHASE62_JSON,
    PHASE62_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase62_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE61_JSON).is_file():
        run_phase61_collection(root)
    art = root / PHASE62_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("numeric_probabilities_used") is False:
            return
    run_phase62_collection(root)


class TestPhase62(unittest.TestCase):
    def test_ranking_is_qualitative(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE62_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["numeric_probabilities_used"])
        ids = {a["id"] for a in payload["actions"]}
        self.assertEqual(ids, {"A", "B", "C", "D", "E", "F", "G", "H"})
        self.assertEqual(len(payload["ranking"]), 8)
        self.assertTrue(str(payload["HIGHEST_VALUE_OPERATOR_ACTION"]).startswith(("A", "B", "C")))
        f_row = next(a for a in payload["actions"] if a["id"] == "F")
        self.assertIn("G1 PASS", f_row["DEPENDENCY"])
        src = (root / "tradingbot/backtest/phase62_operator_action_economics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE62_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        self.assertIn("HIGHEST_VALUE", (root / PHASE62_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
