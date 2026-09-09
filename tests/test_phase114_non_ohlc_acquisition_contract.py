"""Phase 114 non-OHLC acquisition contract tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import (
    CANONICAL_SYMBOL,
    PHASE,
    PHASE40_JSON,
    PHASE114_JSON,
    PHASE114_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase114_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE114_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("data_acquired") is False:
            return
    run_phase114_collection(root)


class TestPhase114(unittest.TestCase):
    def test_contract_not_acquired(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE114_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["CONTRACT_COMPLETE"])
        self.assertTrue(payload["ACQUISITION_READY"])
        self.assertFalse(payload["data_acquired"])
        self.assertFalse(payload["DATA_ACQUIRED"])
        self.assertFalse(payload["mt5_launched"])
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["MT5_USED"])
        self.assertFalse(payload["EXIT_DESIGN_SPEC_IMPLEMENTED"])
        self.assertEqual(payload["horizon"]["symbol"], CANONICAL_SYMBOL)
        self.assertEqual(payload["horizon"]["n_events"], 419)
        self.assertTrue(payload["horizon"]["do_not_alter_frozen_tape"])
        self.assertTrue(payload["tick_contract"]["logical_xauusd_forbidden"])
        self.assertIn("TICK_BID_ASK", payload["DATA_PRIORITY"])
        self.assertEqual(payload["DATA_PRIORITY"][0], "TICK_BID_ASK")
        self.assertFalse(payload["source_options"]["downloaded"])
        ledger = (root / LEDGER_MD).read_text(encoding="utf-8")
        self.assertIn("H114-01", ledger)
        ku = (root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(encoding="utf-8")
        self.assertIn("| Phase 114 started | **YES** |", ku)
        self.assertIn("| Phase 115 started | **NO** |", ku)

    def test_frozen(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE114_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase114_non_ohlc_acquisition_contract.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertNotIn("mt5.initialize", src)
        self.assertIn("ACQUISITION_READY", (root / PHASE114_MD).read_text(encoding="utf-8"))
        self.assertIn("XAUUSD_i", (root / PHASE114_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
