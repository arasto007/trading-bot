"""Phase 57 account-product forensics tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase57_account_product_forensics import (
    PHASE,
    PHASE40_JSON,
    PHASE57_JSON,
    PHASE57_MD,
    REQUIRED_ARTIFACT_KEYS,
    classify_product,
    run_phase57_collection,
)

FORBIDDEN = ("from tradingbot.config.live", "run_phase40_collection(", "symbol_select(")
PHASE40_TS = "2026-09-07T21:09:46Z"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    art = root / PHASE57_JSON
    if art.is_file():
        payload = json.loads(art.read_text(encoding="utf-8"))
        if payload.get("phase") == PHASE and payload.get("DOCUMENT_DATE_CONFLICT") is True:
            return
    run_phase57_collection(root)


class TestPhase57(unittest.TestCase):
    def test_classify_does_not_infer_from_leverage_or_suffix(self) -> None:
        verdict = classify_product(
            {"currency": "USD", "leverage": 100, "limit_orders": 300},
            {"currency": "USD", "margin_so_so": 20},
        )
        self.assertEqual(verdict["ACCOUNT_PRODUCT_CANDIDATE"], "CLASSIC")
        self.assertEqual(verdict["ACCOUNT_PRODUCT"], "PARTIAL")
        self.assertFalse(verdict["inferred_from_leverage"])
        self.assertFalse(verdict["inferred_from_suffix"])
        self.assertFalse(verdict["inferred_from_cl_symbol"])
        self.assertFalse(verdict["inferred_from_zero_commission"])
        self.assertFalse(verdict["inferred_from_cls_path"])
        self.assertIn("ECN", verdict["incompatible_with"])
        self.assertIn("CENT", verdict["incompatible_with"])

    def test_artifact_not_verified_classic(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE57_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["DOCUMENT_DATE_CONFLICT"], True)
        self.assertNotEqual(payload["ACCOUNT_PRODUCT"], "VERIFIED_CLASSIC")
        self.assertNotEqual(payload["ACCOUNT_PRODUCT"], "VERIFIED_ECN")
        self.assertIn(payload["G1"], {"PARTIAL", "FAIL", "UNKNOWN"})
        self.assertNotEqual(payload["G1"], "PASS")
        ident = str(payload["account"].get("login_identity") or "UNKNOWN")
        self.assertTrue(ident.startswith("sha256:") or ident == "UNKNOWN")
        self.assertIn("group", payload["account"]["FIELDS_ABSENT"])
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["mt5_launched"])

    def test_frozen_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE57_JSON).read_text(encoding="utf-8"))
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p40["timestamp_utc"], PHASE40_TS)
        self.assertEqual(p40["tape_fingerprint"], FROZEN)
        src = (root / "tradingbot/backtest/phase57_account_product_forensics.py").read_text(encoding="utf-8")
        for token in FORBIDDEN:
            self.assertNotIn(token, src)
        self.assertIn("PARTIAL", (root / PHASE57_MD).read_text(encoding="utf-8"))
        self.assertFalse(payload["local_search"]["env_read"])
        self.assertFalse(payload["local_search"]["secrets_read"])
        self.assertFalse(payload["local_search"]["proves_this_account"])


if __name__ == "__main__":
    unittest.main()
