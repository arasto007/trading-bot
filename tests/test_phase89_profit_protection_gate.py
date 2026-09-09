"""Phase 89 profit-protection gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, run_phase74_collection
from tradingbot.backtest.phase81_exit_research_gate import PHASE81_JSON, run_phase81_collection
from tradingbot.backtest.phase82_profit_protection_design import PHASE82_JSON, run_phase82_collection
from tradingbot.backtest.phase83_profit_protection_counterfactuals import PHASE83_JSON, run_phase83_collection
from tradingbot.backtest.phase84_tail_preservation import PHASE84_JSON, run_phase84_collection
from tradingbot.backtest.phase85_rescue_vs_destruction import PHASE85_JSON, run_phase85_collection
from tradingbot.backtest.phase86_profit_protection_oos import PHASE86_JSON, run_phase86_collection
from tradingbot.backtest.phase87_profit_protection_interactions import PHASE87_JSON, run_phase87_collection
from tradingbot.backtest.phase88_exit_design_spec import PHASE88_JSON, run_phase88_collection
from tradingbot.backtest.phase89_profit_protection_gate import (
    NEXT_ALLOWED,
    PHASE,
    PHASE40_JSON,
    PHASE89_JSON,
    PHASE89_MD,
    REQUIRED_ARTIFACT_KEYS,
    STATUS_ALLOWED,
    run_phase89_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    if not (root / PHASE74_JSON).is_file():
        run_phase74_collection(root)
    if not (root / PHASE81_JSON).is_file():
        run_phase81_collection(root)
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
    if not (root / PHASE88_JSON).is_file():
        run_phase88_collection(root)
    art = root / PHASE89_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("intervention_implemented") is False:
            return
    run_phase89_collection(root)


class TestPhase89(unittest.TestCase):
    def test_gate_not_implemented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE89_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["PROFIT_PROTECTION_STATUS"], STATUS_ALLOWED)
        self.assertIn(payload["NEXT_RESEARCH_TARGET"], NEXT_ALLOWED)
        self.assertFalse(payload["intervention_implemented"])
        self.assertFalse(payload["PARAMETER_SEARCH_USED"])
        self.assertFalse(payload["OPTIMIZATION_USED"])
        self.assertFalse(payload["PRODUCTION_CHANGED"])
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["LIVE_TRADING"])
        self.assertFalse(payload["oos_used_for_selection"])
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H82-01", ledger)
        self.assertIn("H89-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 82 started | **YES** |", ku)
        self.assertIn("Phase 90 started", ku)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE89_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase89_profit_protection_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("NEXT_RESEARCH_TARGET", (root / PHASE89_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
