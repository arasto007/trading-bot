"""Phase 86 profit-protection OOS consistency tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase82_profit_protection_design import PHASE82_JSON, run_phase82_collection
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, run_phase83_collection
from tradingbot.backtest.phase84_tail_preservation import PHASE84_JSON, run_phase84_collection
from tradingbot.backtest.phase86_profit_protection_oos import (
    PHASE,
    PHASE40_JSON,
    PHASE86_JSON,
    PHASE86_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase86_collection,
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
    if not (root / PHASE84_JSON).is_file():
        run_phase84_collection(root)
    art = root / PHASE86_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("oos_used_for_selection") is False:
            return
    run_phase86_collection(root)


class TestPhase86(unittest.TestCase):
    def test_folds_reported_not_used_to_select(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE86_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["oos_used_for_selection"])
        self.assertTrue(payload["official_baseline_unchanged"])
        self.assertTrue(payload["top1_top5_are_diagnostics_only"])
        row = payload["by_family"]["PEAK_RETRACE_EXIT"]
        for fold in ("TRAIN", "VALIDATION", "OOS", "RECENT_180D", "WITHOUT_TOP1", "WITHOUT_TOP5"):
            self.assertIn(fold, row["folds"])
        self.assertIn("TRAIN_improves", row)
        self.assertIsInstance(payload["survivors"], list)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE86_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase86_profit_protection_oos.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("OOS reported", (root / PHASE86_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
