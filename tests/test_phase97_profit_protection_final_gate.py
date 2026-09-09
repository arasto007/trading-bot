"""Phase 97 profit-protection final gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase95_protection_family_v2 import PHASE95_JSON, run_phase95_collection
from tradingbot.backtest.phase96_protection_robustness_gate import PHASE96_JSON, run_phase96_collection
from tradingbot.backtest.phase97_profit_protection_final_gate import (
    GATE_ALLOWED,
    NEXT_ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE97_JSON,
    PHASE97_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase97_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE95_JSON).is_file():
        run_phase95_collection(root)
    if not (root / PHASE96_JSON).is_file():
        run_phase96_collection(root)
    art = root / PHASE97_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("intervention_implemented") is False:
            return
    run_phase97_collection(root)


class TestPhase97(unittest.TestCase):
    def test_gate_not_implemented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE97_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["PROTECTION_STATUS"], GATE_ALLOWED)
        self.assertIn(payload["NEXT_RESEARCH_TARGET"], NEXT_ALLOWED)
        self.assertFalse(payload["intervention_implemented"])
        self.assertFalse(payload["PARAMETER_SEARCH_USED"])
        self.assertFalse(payload["PRODUCTION_CHANGED"])
        self.assertFalse(payload["MT5_USED"])
        if not payload.get("production_candidates"):
            self.assertEqual(payload["EXIT_DESIGN_SPEC"], "INSUFFICIENT_EVIDENCE")
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H90-01", ledger)
        self.assertIn("H97-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 90 started | **YES** |", ku)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE97_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase97_profit_protection_final_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("EXIT_DESIGN_SPEC", (root / PHASE97_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
