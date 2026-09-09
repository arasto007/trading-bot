"""Phase 77 exit-geometry forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase77_exit_geometry_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE77_JSON,
    PHASE77_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase77_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    art = root / PHASE77_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase77_collection(root)


class TestPhase77(unittest.TestCase):
    def test_rr_class_and_baseline_kept(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE77_JSON).read_text(encoding="utf-8"))
        self.assertGreaterEqual(payload["high_rr_class"]["n"], 2)
        self.assertFalse(payload["extreme_winner_kept"]["removed_from_baseline"])
        self.assertIn("2026-01-21", str(payload["extreme_winner_kept"]["timestamp"]))
        self.assertIn("LEGITIMATE", payload["HIGH_PLANNED_RR_IS"])
        self.assertFalse(payload["parameters_optimized"])

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE77_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase77_exit_geometry_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("HIGH_PLANNED_RR_IS", (root / PHASE77_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
