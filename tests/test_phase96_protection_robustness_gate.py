"""Phase 96 protection robustness gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase95_protection_family_v2 import PHASE95_JSON, run_phase95_collection
from tradingbot.backtest.phase96_protection_robustness_gate import (
    PHASE,
    PHASE40_JSON,
    PHASE96_JSON,
    PHASE96_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase96_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
CLASSES = {"PRODUCTION_CANDIDATE", "RESEARCH_ONLY", "REJECTED", "DATA_LIMITED"}


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE95_JSON).is_file():
        run_phase95_collection(root)
    art = root / PHASE96_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("parameters_optimized") is False:
            return
    run_phase96_collection(root)


class TestPhase96(unittest.TestCase):
    def test_qualitative_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE96_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["parameters_optimized"])
        self.assertGreaterEqual(len(payload["by_family"]), 4)
        for row in payload["by_family"].values():
            self.assertIn(row["class"], CLASSES)
            self.assertEqual(row["threshold_perturbation"], "NOT_PERFORMED_WOULD_BE_SEARCH")
            self.assertFalse(row["future_information"])
            self.assertTrue(row["event_cluster_unit"])
            self.assertEqual(row["bootstrap"]["seed"], 400040)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE96_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase96_protection_robustness_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("Qualitative scores", (root / PHASE96_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
