"""Phase 35 — execution reality tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_15_cost_completeness_gate import GATE_COMPONENTS
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase35_execution_reality import (
    BLOCKED,
    INCOMPLETE,
    MODELED,
    PHASE,
    PHASE35_JSON,
    PHASE35_MD,
    REQUIRED_ARTIFACT_KEYS,
    UNKNOWN,
    VERIFIED,
    run_phase35_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    "bounded_readonly_attach_once",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase35_collection(Path(__file__).resolve().parents[1])


class TestPhase35ExecutionReality(unittest.TestCase):
    def test_grades_and_no_modeled_to_verified(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE35_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["live_orders"])
        self.assertFalse(payload["modeled_converted_to_verified"])
        comps = payload["cost_components"]
        for name in GATE_COMPONENTS:
            self.assertIn(name, comps)
            self.assertIn("grade", comps[name])
            self.assertIn("and_status", comps[name])
        self.assertNotEqual(payload["slippage"]["grade"], VERIFIED)
        self.assertIn(payload["slippage"]["grade"], {MODELED, UNKNOWN})
        self.assertEqual(payload["slippage"]["genuine_requested_vs_executed_pairs"], 0)
        self.assertFalse(payload["slippage"]["mt5_deviation_is_realized_slippage"])
        self.assertTrue(payload["slippage"]["modeled_not_converted_to_verified"])
        self.assertEqual(payload["spread"]["production_parquet"]["grade"], "PROXY")
        self.assertFalse(payload["commission"]["account_specific_schedule"])
        self.assertTrue(payload["commission"]["deal_tape"]["zero_is_not_verified_zero"])
        self.assertFalse(payload["swap"]["deal_zeros_prove_historical_zero"])
        self.assertFalse(payload["execution"]["pairs_fabricated"])
        for key in ("minimum_lot", "volume_step", "contract_size", "tick_value", "tick_size"):
            self.assertEqual(payload["economics_contract"][key], UNKNOWN)

    def test_and_gate_incomplete_no_phase_36(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE35_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["cost_completeness"]["classification"], INCOMPLETE)
        self.assertFalse(payload["cost_completeness"]["and_satisfied"])
        self.assertEqual(payload["cost_completeness"]["complete_count"], 0)
        self.assertFalse(payload["cost_completeness"]["theoretical_edge_survives_broker_economics"])
        self.assertEqual(payload["cost_completeness"]["theoretical_edge_claim"], "NOT_PROVEN")
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_36_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertTrue(payload["reproducibility"]["passes_match"])
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase35_execution_reality.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE35_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 35", md)
        self.assertIn("DO NOT START PHASE 36", md)
        self.assertIn("INCOMPLETE", md)
        self.assertNotIn("phase36_", src.lower())
        spread = payload["spread"]["sidecar_tape"]
        if spread.get("meta", {}).get("bid_ask_columns"):
            for key in ("median", "p75", "p90", "p95", "p99"):
                self.assertIn(key, spread["overall"]["price"])
                self.assertIn(key, spread["ny_open_hour_15_utc"]["price"])
