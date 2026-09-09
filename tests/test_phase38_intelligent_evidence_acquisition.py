"""Phase 38 — intelligent evidence acquisition tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import (
    BLOCKED,
    EVIDENCE_IDS,
    PHASE,
    PHASE38_JSON,
    PHASE38_M5,
    PHASE38_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase38_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "get_mt5_credentials",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / PHASE38_JSON
    tape = root / PHASE38_M5
    if artifact.is_file() and tape.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if payload.get("event_sufficiency", {}).get("ran") is True and payload.get(
            "fingerprints", {}
        ).get("phase28_m5_unchanged") and int(
            payload.get("event_sufficiency", {}).get("setups_missing_asian_range") or 0
        ) == 0 and (root / "logs" / "phase38_raw_setups.json").is_file():
            return
    run_phase38_collection(root)


class TestPhase38IntelligentEvidenceAcquisition(unittest.TestCase):
    def test_gap_matrix_frozen_tape_and_no_silent_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE38_JSON).read_text(encoding="utf-8"))
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertTrue(payload["fingerprints"]["phase28_m5_unchanged"])
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertTrue(payload["dataset_binding"]["empty_map"])
        self.assertFalse(payload["dataset_binding"]["xauusd_merged"])
        self.assertEqual(payload["ev_eq_01"], "NOT_PROVEN")
        ids = {row["evidence_id"] for row in payload["gap_matrix"]}
        for evid in EVIDENCE_IDS:
            self.assertIn(evid, ids)
        self.assertNotEqual(PHASE38_M5, CANONICAL_PARQUET)
        self.assertFalse(payload["cost_completeness"]["gate_weakened"])
        self.assertFalse(payload["cost_completeness"]["cost_ready_for_validation"])
        self.assertEqual(payload["slippage"]["status"], "MODELED")
        self.assertFalse(payload["slippage"]["mt5_deviation_is_realized_slippage"])
        self.assertTrue(payload["commission"]["zero_is_not_verified"])

    def test_safety_no_env_no_phase_39(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE38_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["safety"]["BOT_STARTED"])
        self.assertFalse(payload["safety"]["ORDERS_SENT"])
        self.assertFalse(payload["safety"]["SYMBOL_SELECT"])
        self.assertFalse(payload["safety"]["ENV_ACCESSED"])
        self.assertFalse(payload["phase_39_started"])
        self.assertEqual(payload["production_changes"], "NONE")
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        self.assertIn(payload["BLOCKER_REMAINING"], {"YES", "NO"})
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotRegex(raw.lower(), rf'"{secret}"\s*:')
        src = (root / "tradingbot" / "backtest" / "phase38_intelligent_evidence_acquisition.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE38_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 38", md)
        self.assertIn("DO NOT START PHASE 39", md)
        self.assertNotIn("phase39_", src.lower())
        disc = payload["mt5_discovery"]
        self.assertIn("installations", disc)
        self.assertIn("selection", disc)
        self.assertIn("launch", disc)
        self.assertFalse(payload["execution"]["positions_touched"])
        self.assertFalse(payload["execution"]["orders_modified"])
        self.assertNotEqual(str(payload["symbols"]["XAUUSD"].get("existence")), "DOES_NOT_EXIST_BROKER_WIDE")
        self.assertEqual(payload["symbols"]["XAUUSD"].get("broker_wide_absence_concluded"), False)
        if float(payload.get("m5", {}).get("days") or 0) >= 60:
            self.assertTrue(payload["event_sufficiency"]["ran"])
            self.assertIsInstance(payload["event_sufficiency"]["event_count"], int)
            self.assertFalse(payload["event_sufficiency"].get("independence_manufactured"))
            self.assertTrue((root / PHASE38_M5).is_file())
        self.assertNotIn(payload.get("status"), {"PROFITABLE", "UNPROFITABLE"})
        self.assertEqual(payload["strategy_evaluation"].get("optimized"), False)
        self.assertIn("This is **not** a production strategy verdict", md)
