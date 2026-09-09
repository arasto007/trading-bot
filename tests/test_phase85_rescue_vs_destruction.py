"""Phase 85 rescue vs destruction tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase82_profit_protection_design import PHASE82_JSON, run_phase82_collection
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, run_phase83_collection
from tradingbot.backtest.phase85_rescue_vs_destruction import (
    PHASE,
    PHASE40_JSON,
    PHASE85_JSON,
    PHASE85_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase85_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE82_JSON).is_file():
        run_phase82_collection(root)
    if not (root / PHASE83_JSON).is_file():
        run_phase83_collection(root)
    art = root / PHASE85_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase85_collection(root)


class TestPhase85(unittest.TestCase):
    def test_rescue_and_destruction_reported(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE85_JSON).read_text(encoding="utf-8"))
        row = payload["by_family"]["PEAK_RETRACE_EXIT"]
        self.assertIn("to_ge_0R", row["LOSER_RESCUE"])
        self.assertIn("to_le_0R", row["WINNER_DESTRUCTION"])
        self.assertIn("materially_reduced", row["TAIL_DESTRUCTION"])
        self.assertTrue(row["not_selected_by_expectancy_alone"])
        self.assertEqual(payload["by_family"]["ATR_NORMALIZED_RETRACE"]["status"], "DATA_LIMITED")
        self.assertFalse(payload["parameters_optimized"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE85_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase85_rescue_vs_destruction.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("Loser Rescue", (root / PHASE85_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
