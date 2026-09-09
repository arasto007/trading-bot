"""Phase 41 — final evidence closure tests (no Phase 40 rescan)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import PHASE38_M5
from tradingbot.backtest.phase40_full_horizon_validation import PHASE40_JSON
from tradingbot.backtest.phase41_final_evidence_closure import (
    EXPECTED_PHASE40,
    PHASE,
    PHASE41_BLOCKERS_MD,
    PHASE41_JSON,
    PHASE41_MD,
    REQUIRED_ARTIFACT_KEYS,
    run_phase41_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "get_mt5_credentials",
    "MetaTrader5.initialize",
    "mt5.initialize",
)


def setUpModule() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact = root / PHASE41_JSON
    if artifact.is_file():
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        if (
            payload.get("phase") == PHASE
            and payload.get("phase40_scan_rerun") is False
            and payload.get("FINAL_GATE") == BLOCKED
            and (root / PHASE41_MD).is_file()
            and (root / PHASE41_BLOCKERS_MD).is_file()
        ):
            return
    run_phase41_collection(root)


class TestPhase41FinalEvidenceClosure(unittest.TestCase):
    def test_phase40_facts_preserved_no_rescan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE41_JSON).read_text(encoding="utf-8"))
        p40 = json.loads((root / PHASE40_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["phase40_scan_rerun"])
        self.assertTrue(payload["phase40_verification"]["matches_expected_facts"])
        self.assertFalse(payload["phase40_verification"]["values_overwritten"])
        self.assertEqual(p40["scan"]["tape_rows_loaded"], EXPECTED_PHASE40["tape_rows_loaded"])
        self.assertEqual(p40["scan"]["signals"], EXPECTED_PHASE40["signals"])
        self.assertEqual((p40.get("events") or {}).get("event_count"), EXPECTED_PHASE40["events"])
        self.assertEqual(p40["FINAL_GATE"], BLOCKED)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertNotEqual(PHASE38_M5, CANONICAL_PARQUET)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertEqual(payload["commission"]["status"], "UNKNOWN")
        self.assertFalse(payload["commission"]["verified_schedule"])
        self.assertTrue(payload["commission"]["zero_is_not_verified"])
        self.assertEqual(payload["request_fill"]["pairs"], 0)
        self.assertEqual(payload["executable"]["status"], "NOT_ESTABLISHED")
        self.assertEqual(payload["cost_margin"]["COST_MARGIN"], "INSUFFICIENT / UNKNOWN")
        self.assertEqual(payload["symbol"]["SYMBOL_MAPPING"], "NOT_PROVEN")
        self.assertFalse(payload["symbol"]["broker_wide_absence_concluded"])
        self.assertEqual(payload["spread"]["SPREAD_POLICY"], "PROXY / PARTIAL")
        self.assertEqual(payload["slippage"]["SLIPPAGE_POLICY"], "MODELED")
        self.assertEqual(payload["verdict"]["G_OVERALL_RESEARCH_VERDICT"]["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(payload["profitability_verdict"], "NOT_ISSUED")
        self.assertTrue(payload["verdict"]["bootstrap_ci_crosses_zero"])
        self.assertGreaterEqual(len(payload["blockers"]), 8)
        self.assertGreaterEqual(len(payload["evidence_matrix"]), 20)

    def test_safety_no_env_no_phase_42(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE41_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["production_safety"]["BOT_STARTED"])
        self.assertFalse(payload["production_safety"]["ORDERS_SENT"])
        self.assertFalse(payload["production_safety"]["ENV_READ"])
        self.assertFalse(payload["production_safety"]["MT5_STARTED"])
        self.assertFalse(payload["phase_42_started"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["prior_phase16_final_gate"], "BLOCKED")
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["production_safety"]["production_changes"], "NONE")
        self.assertEqual(payload["production_safety"]["TRADING"], "NOT_PERFORMED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotRegex(raw.lower(), rf'"{secret}"\s*:')
        src = (root / "tradingbot" / "backtest" / "phase41_final_evidence_closure.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertNotIn("import run_phase40_collection", src)
        self.assertNotIn("run_phase42_collection", src)
        md = (root / PHASE41_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 41", md)
        self.assertIn("DO NOT START PHASE 42", md)
        self.assertIn("does **not** issue PROFITABLE", md)
        blockers = (root / PHASE41_BLOCKERS_MD).read_text(encoding="utf-8")
        self.assertIn("Commission unknown", blockers)
        self.assertIn("Request/fill pairs absent", blockers)
