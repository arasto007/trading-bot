"""Phase 59 symbol-equivalence forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase54_account_broker_evidence import compare_identity
from tradingbot.backtest.phase59_symbol_equivalence_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE59_JSON,
    PHASE59_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase59_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE59_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("broker_wide_absence_concluded") is False:
            return
    run_phase59_collection(root)


class TestPhase59(unittest.TestCase):
    def test_absence_is_not_broker_absent_or_contradicted(self) -> None:
        identity = compare_identity(
            {"existence": "NOT_OBSERVED_ON_THIS_TERMINAL"},
            {"existence": "YES", "contract_size": 100},
        )
        self.assertEqual(identity["IDENTITY_STATUS"], "NOT_PROVEN")
        self.assertEqual(identity["CURRENT_TERMINAL_XAUUSD"], "NOT_OBSERVED")
        self.assertFalse(identity["broker_wide_absence_concluded"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE59_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["broker_wide_absence_concluded"])
        self.assertFalse(payload["path_analysis"]["proves_equivalence"])
        self.assertFalse(payload["path_analysis"]["proves_account_type"])
        self.assertEqual(payload["path_analysis"]["classification"], "SUPPORTING_EVIDENCE")
        self.assertFalse(payload["official_xauusd_page"]["explicit_alias_statement_for_XAUUSD_i"])
        self.assertFalse(payload["official_cabinet_xauusd"]["explicit_alias_statement_for_XAUUSD_i"])
        if payload["XAUUSD_CURRENT_TERMINAL"] == "NOT_OBSERVED":
            self.assertEqual(payload["SYMBOL_MAPPING"], "NOT_PROVEN")
            self.assertEqual(payload["G3"], "FAIL")
        self.assertNotEqual(payload["SYMBOL_MAPPING"], "PROVEN")

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE59_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["datasets_renamed"])
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["mt5_launched"])
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase59_symbol_equivalence_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        live = (root / "tradingbot/config/live.py").read_text(encoding="utf-8")
        self.assertIn('PRIMARY_SYMBOL = "XAUUSD_i"', live)
        self.assertEqual(payload["code_research_symbol"], "XAUUSD_i")
        self.assertIn("NOT_OBSERVED", (root / PHASE59_MD).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
