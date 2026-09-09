"""Phase 84 tail preservation tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase82_profit_protection_design import PHASE82_JSON, run_phase82_collection
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, run_phase83_collection
from tradingbot.backtest.phase84_tail_preservation import (
    ALLOWED_TAIL,
    PHASE,
    PHASE40_JSON,
    PHASE84_JSON,
    PHASE84_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase84_collection,
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
    art = root / PHASE84_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase84_collection(root)


class TestPhase84(unittest.TestCase):
    def test_outlier_is_diagnostic(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE84_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["outlier_kept_in_baseline"])
        self.assertFalse(payload["production_safety"]["baseline_rewritten"])
        fam = payload["by_family"]["PEAK_RETRACE_EXIT"]
        self.assertIn("2026-01-21", str((fam.get("outlier") or {}).get("timestamp")))
        for name, row in payload["by_family"].items():
            self.assertIn(row.get("TAIL_PRESERVATION"), ALLOWED_TAIL)
            if name != "ATR_NORMALIZED_RETRACE":
                self.assertTrue(row.get("not_retuned_to_save_outlier", True))
        self.assertEqual(payload["by_family"]["ATR_NORMALIZED_RETRACE"]["TAIL_PRESERVATION"], "DATA_LIMITED")

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE84_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase84_tail_preservation.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("TAIL_PRESERVATION", (root / PHASE84_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
