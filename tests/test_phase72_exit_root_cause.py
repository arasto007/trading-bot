"""Phase 72 exit root-cause tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase68_exit_forensics import PHASE68_JSON, run_phase68_collection
from tradingbot.backtest.phase69_exit_geometry import PHASE69_JSON, run_phase69_collection
from tradingbot.backtest.phase70_exit_counterfactuals import PHASE70_JSON, run_phase70_collection
from tradingbot.backtest.phase71_extreme_winner_forensics import PHASE71_JSON, run_phase71_collection
from tradingbot.backtest.phase72_exit_root_cause import (
    CANDIDATES,
    PHASE,
    PHASE40_JSON,
    PHASE72_JSON,
    PHASE72_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase72_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE68_JSON).is_file():
        run_phase68_collection(root)
    if not (root / PHASE69_JSON).is_file():
        run_phase69_collection(root)
    if not (root / PHASE70_JSON).is_file():
        run_phase70_collection(root)
    if not (root / PHASE71_JSON).is_file():
        run_phase71_collection(root)
    art = root / PHASE72_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("copied_phase67") is False:
            return
    run_phase72_collection(root)


class TestPhase72(unittest.TestCase):
    def test_reranked_causes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE72_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["copied_phase67"])
        self.assertEqual(payload["PRIMARY_CAUSE"], "PROFIT_GIVEBACK")
        self.assertEqual(payload["SECONDARY_CAUSE"], "EXIT_GEOMETRY")
        self.assertEqual(payload["TERTIARY_CAUSE"], "EXTREME_OUTLIER_DEPENDENCY")
        for name in CANDIDATES:
            self.assertIn(name, payload["matrix"])
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertNotEqual(payload["PRIMARY_CAUSE"], "EXIT_PROBLEM")

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE72_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase72_exit_root_cause.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("PRIMARY_CAUSE", (root / PHASE72_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
