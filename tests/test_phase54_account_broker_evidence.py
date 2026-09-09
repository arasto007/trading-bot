"""Phase 54 account/broker evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase54_account_broker_evidence import (
    FROZEN_TAPE_FINGERPRINT,
    PHASE,
    PHASE40_JSON,
    PHASE54_JSON,
    PHASE54_MD,
    REQUIRED_ARTIFACT_KEYS,
    compare_identity,
    run_phase54_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE54_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("commission", {}).get("zero_converted_to_schedule") is False:
            return
    run_phase54_collection(root)


class TestPhase54(unittest.TestCase):
    def test_commission_zeros_not_schedule(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE54_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["commission"]["zero_converted_to_schedule"])
        self.assertFalse(payload["commission"]["VERIFIED_SCHEDULE"])
        self.assertIn(
            payload["commission"]["OBSERVED_COMMISSION_STATUS"],
            {"ZERO_OBSERVED_NOT_PROVEN", "NONZERO_OBSERVED", "UNKNOWN"},
        )
        self.assertEqual(payload["official_docs"]["applicability_to_exact_account"], "UNKNOWN")
        self.assertFalse(payload["product"]["inferred_from_zeros"])

    def test_absent_xauusd_is_not_contradicted(self) -> None:
        identity = compare_identity(
            {"existence": "NOT_OBSERVED_ON_THIS_TERMINAL"},
            {"existence": "YES", "contract_size": 100},
        )
        self.assertEqual(identity["IDENTITY_STATUS"], "NOT_PROVEN")
        self.assertEqual(identity["CURRENT_TERMINAL_XAUUSD"], "NOT_OBSERVED")
        self.assertFalse(identity["broker_wide_absence_concluded"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE54_JSON).read_text(encoding="utf-8"))
        if payload["identity"]["CURRENT_TERMINAL_XAUUSD"] == "NOT_OBSERVED":
            self.assertNotEqual(payload["identity"]["IDENTITY_STATUS"], "CONTRADICTED")
            self.assertEqual(payload["identity"]["EV_EQ_01"], "NOT_PROVEN")

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE54_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["mt5_launched"])
        self.assertFalse(payload["phase40_scan_rerun"])
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN_TAPE_FINGERPRINT)
        src = (root / "tradingbot/backtest/phase54_account_broker_evidence.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("VERIFIED_SCHEDULE", (root / PHASE54_MD).read_text(encoding="utf-8"))
        ident = str(payload["account"].get("login_identity") or "UNKNOWN")
        self.assertTrue(ident.startswith("sha256:") or ident == "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
