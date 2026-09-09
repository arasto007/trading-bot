"""Phase 88 exit design spec tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase82_profit_protection_design import PHASE82_JSON, run_phase82_collection
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, run_phase83_collection
from tradingbot.backtest.phase84_tail_preservation import PHASE84_JSON, run_phase84_collection
from tradingbot.backtest.phase85_rescue_vs_destruction import PHASE85_JSON, run_phase85_collection
from tradingbot.backtest.phase86_profit_protection_oos import PHASE86_JSON, run_phase86_collection
from tradingbot.backtest.phase87_profit_protection_interactions import PHASE87_JSON, run_phase87_collection
from tradingbot.backtest.phase88_exit_design_spec import (
    INSUFFICIENT,
    PHASE,
    PHASE40_JSON,
    PHASE88_JSON,
    PHASE88_MD,
    REQUIRED_ARTIFACT_KEYS,
    pick_design,
    run_phase88_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
ALLOWED = {
    INSUFFICIENT,
    "PEAK_RETRACE_EXIT",
    "MFE_FRACTION_FLOOR",
    "SWING_PROTECTION",
    "HYBRID",
}


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE82_JSON).is_file():
        run_phase82_collection(root)
    if not (root / PHASE83_JSON).is_file():
        run_phase83_collection(root)
    if not (root / PHASE84_JSON).is_file():
        run_phase84_collection(root)
    if not (root / PHASE85_JSON).is_file():
        run_phase85_collection(root)
    if not (root / PHASE86_JSON).is_file():
        run_phase86_collection(root)
    if not (root / PHASE87_JSON).is_file():
        run_phase87_collection(root)
    art = root / PHASE88_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("implemented_in_production") is False:
            return
    run_phase88_collection(root)


class TestPhase88(unittest.TestCase):
    def test_spec_not_implemented(self) -> None:
        chosen, _reason = pick_design({"helpful_families": []}, {}, {}, {"survivors": []})
        self.assertEqual(chosen, INSUFFICIENT)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE88_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["EXIT_DESIGN_SPEC"], ALLOWED)
        self.assertFalse(payload["implemented_in_production"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertFalse(payload["production_safety"]["spec_implemented"])
        self.assertFalse(payload["spec"]["forced"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE88_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase88_exit_design_spec.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("DO NOT IMPLEMENT", (root / PHASE88_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
