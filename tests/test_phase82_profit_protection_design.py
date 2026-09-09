"""Phase 82 profit-protection design taxonomy tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase82_profit_protection_design import (
    PHASE,
    PHASE40_JSON,
    PHASE82_JSON,
    PHASE82_MD,
    REQUIRED_ARTIFACT_KEYS,
    STRUCTURAL_FRACTION,
    run_phase82_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE82_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase82_collection(root)


class TestPhase82(unittest.TestCase):
    def test_taxonomy_predeclared(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE82_JSON).read_text(encoding="utf-8"))
        tax = payload["taxonomy"]
        for key in (
            "A_MFE_PERCENTAGE_PROTECTION",
            "B_PEAK_TO_CURRENT_RETRACEMENT",
            "C_STRUCTURAL_SWING_PROTECTION",
            "D_VOLATILITY_NORMALIZED_PROTECTION",
            "E_HYBRID",
        ):
            self.assertIn(key, tax)
            self.assertIn("causal_rationale", tax[key])
            self.assertIn("required_data", tax[key])
            self.assertIn("available_data", tax[key])
            self.assertIn("unavailable_data", tax[key])
            self.assertIn("right_tail_risk", tax[key])
        self.assertEqual(tax["D_VOLATILITY_NORMALIZED_PROTECTION"]["status"], "DATA_LIMITED")
        self.assertTrue(tax["D_VOLATILITY_NORMALIZED_PROTECTION"]["parameter_unresolved"])
        self.assertFalse(tax["E_HYBRID"]["created_automatically"])
        self.assertEqual(payload["STRUCTURAL_FRACTION"], 0.5)
        self.assertEqual(STRUCTURAL_FRACTION, 0.5)
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["grid_search"])
        self.assertFalse(payload["atr_on_tape"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE82_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase82_profit_protection_design.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("Causal rationale", (root / PHASE82_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
