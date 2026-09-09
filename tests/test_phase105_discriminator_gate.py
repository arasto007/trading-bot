"""Phase 105 discriminator gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase104_minimal_discriminator import PHASE104_JSON, run_phase104_collection
from tradingbot.backtest.phase105_discriminator_gate import (
    GATE_ALLOWED,
    NEXT_ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE105_JSON,
    PHASE105_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase105_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    from tradingbot.backtest.phase98_first_favorable_state import PHASE98_JSON, run_phase98_collection
    from tradingbot.backtest.phase99_path_velocity_persistence import PHASE99_JSON, run_phase99_collection
    from tradingbot.backtest.phase100_retrace_expansion_forensics import PHASE100_JSON, run_phase100_collection
    from tradingbot.backtest.phase101_entry_vs_exit import PHASE101_JSON, run_phase101_collection
    from tradingbot.backtest.phase102_cluster_timing_forensics import PHASE102_JSON, run_phase102_collection
    from tradingbot.backtest.phase103_structure_at_retracement import PHASE103_JSON, run_phase103_collection

    if not (root / PHASE98_JSON).is_file():
        run_phase98_collection(root)
    if not (root / PHASE99_JSON).is_file():
        run_phase99_collection(root)
    if not (root / PHASE100_JSON).is_file():
        run_phase100_collection(root)
    if not (root / PHASE101_JSON).is_file():
        run_phase101_collection(root)
    if not (root / PHASE102_JSON).is_file():
        run_phase102_collection(root)
    if not (root / PHASE103_JSON).is_file():
        run_phase103_collection(root)
    if not (root / PHASE104_JSON).is_file():
        run_phase104_collection(root)
    art = root / PHASE105_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("intervention_implemented") is False:
            return
    run_phase105_collection(root)


class TestPhase105(unittest.TestCase):
    def test_gate_not_implemented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE105_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["DISCRIMINATOR_STATUS"], GATE_ALLOWED)
        self.assertIn(payload["NEXT_RESEARCH_TARGET"], NEXT_ALLOWED)
        self.assertFalse(payload["intervention_implemented"])
        self.assertFalse(payload["PARAMETER_SEARCH_USED"])
        self.assertFalse(payload["PRODUCTION_CHANGED"])
        self.assertFalse(payload["MT5_USED"])
        self.assertEqual(payload["EXIT_DESIGN_SPEC_STATUS"], "INSUFFICIENT_EVIDENCE")
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H98-01", ledger)
        self.assertIn("H105-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 98 started | **YES** |", ku)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE105_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase105_discriminator_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("DISCRIMINATOR_STATUS", (root / PHASE105_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
