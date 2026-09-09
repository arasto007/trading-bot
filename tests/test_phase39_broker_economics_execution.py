"""Phase 39 — broker economics and execution evidence tests."""

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
from tradingbot.backtest.phase38_intelligent_evidence_acquisition import PHASE38_M5
from tradingbot.backtest.phase39_broker_economics_execution import (
    BLOCKED,
    PHASE,
    PHASE39_JSON,
    PHASE39_MD,
    REQUIRED_ARTIFACT_KEYS,
    SENSITIVITY_DECLARATION,
    WALKFORWARD_DECLARATION,
    run_phase39_collection,
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
    run_phase39_collection(Path(__file__).resolve().parents[1])


class TestPhase39BrokerEconomicsExecution(unittest.TestCase):
    def test_frozen_tape_gate_and_no_silent_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE39_JSON).read_text(encoding="utf-8"))
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertTrue(payload["fingerprints"]["phase28_m5_unchanged"])
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertTrue(payload["dataset_binding"]["empty_map"])
        self.assertFalse(payload["dataset_binding"]["xauusd_merged"])
        self.assertEqual(payload["ev_eq_01"], "NOT_PROVEN")
        self.assertNotEqual(PHASE38_M5, CANONICAL_PARQUET)
        self.assertFalse(payload["cost_completeness"]["gate_weakened"])
        self.assertFalse(payload["cost_completeness"]["cost_ready_for_validation"])
        self.assertEqual(payload["cost_completeness"]["complete_count"], 0)
        self.assertEqual(payload["slippage"]["status"], "MODELED")
        self.assertFalse(payload["slippage"]["price_open_is_requested"])
        self.assertTrue(payload["commission"]["zero_is_not_verified"])
        self.assertFalse(payload["commission"]["verified_schedule"])
        self.assertFalse(payload["spread"]["ohlc_proxy_relabeled_observed"])
        self.assertIn(payload["case"]["case"], {"A", "B", "C"})
        self.assertFalse(payload["case"]["forced_A"])
        self.assertFalse(payload["cost_adjusted_broker_realistic"])
        self.assertEqual((payload.get("statistics") or {}).get("profitability_verdict"), "NOT_ISSUED")
        self.assertTrue(WALKFORWARD_DECLARATION["declared_before_metrics"])
        self.assertTrue(SENSITIVITY_DECLARATION["declared_before_metrics"])
        self.assertEqual(payload["symbols"]["XAUUSD"].get("broker_wide_absence_concluded"), False)
        self.assertNotEqual(str(payload["symbols"]["XAUUSD"].get("existence")), "DOES_NOT_EXIST_BROKER_WIDE")
        self.assertFalse((payload.get("research") or {}).get("logical_xauusd_used", True))

    def test_safety_no_env_no_phase_40(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE39_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["env_accessed"])
        self.assertFalse(payload["safety"]["BOT_STARTED"])
        self.assertFalse(payload["safety"]["ORDERS_SENT"])
        self.assertFalse(payload["safety"]["SYMBOL_SELECT"])
        self.assertFalse(payload["phase_40_started"])
        self.assertEqual(payload["production_changes"], "NONE")
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotRegex(raw.lower(), rf'"{secret}"\s*:')
        src = (root / "tradingbot" / "backtest" / "phase39_broker_economics_execution.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertNotIn("phase40_", src.lower())
        md = (root / PHASE39_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 39", md)
        self.assertIn("DO NOT START PHASE 40", md)
        self.assertIn("does **not** issue a profitability verdict", md)
        self.assertFalse(payload["execution"]["positions_touched"])
        self.assertFalse(payload["execution"]["orders_modified"])
        self.assertEqual((payload.get("research") or {}).get("optimized"), False)
