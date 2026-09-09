"""Phase 27.32 — final integrated cost-evidence gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_15_cost_completeness_gate import GATE_COMPONENTS
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_32_final_cost_evidence_gate import (
    BLOCKED,
    COMPLETE,
    PHASE2732_JSON,
    PHASE2732_MD,
    REQUIRED_ARTIFACT_KEYS,
    and_complete,
    cannot_silent_map_xauusd,
    cannot_treat_current_swap_as_historical,
    cannot_treat_modeled_as_realized,
    cannot_treat_observed_zero_as_verified,
    cannot_upgrade_partial_coverage_to_complete,
    run_phase27_32_collection,
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
    run_phase27_32_collection(Path(__file__).resolve().parents[1])


class TestPhase2732FinalCostEvidenceGate(unittest.TestCase):
    def test_and_gate_and_forbidden_upgrades(self) -> None:
        self.assertEqual(and_complete(["UNKNOWN", "PARTIAL", "BLOCKED"]), BLOCKED)
        self.assertEqual(and_complete([COMPLETE] * 8), COMPLETE)
        self.assertTrue(cannot_upgrade_partial_coverage_to_complete("PARTIAL_CANONICAL_COVERAGE"))
        self.assertTrue(cannot_treat_observed_zero_as_verified("OBSERVED_ZERO_NOT_PROVEN"))
        self.assertTrue(cannot_treat_current_swap_as_historical(False))
        self.assertTrue(cannot_treat_modeled_as_realized())
        self.assertTrue(cannot_silent_map_xauusd())
        self.assertEqual(LOCKED_POLICY["DECISION_6"], "COMPLETE_COSTS_REQUIRED")

    def test_no_component_is_complete_and_gate_blocked(self) -> None:
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2732_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["complete_costs_required_result"], BLOCKED)
        self.assertFalse(payload["cost_ready_for_validation"])
        self.assertFalse(payload["cost_adjusted_metrics_allowed"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["production_readiness"], BLOCKED)
        self.assertEqual(payload["gate_and_complete_count"], 0)
        self.assertEqual(len(payload["gate_and_incomplete"]), 8)
        self.assertEqual(list(payload["gate_and_components"]), list(GATE_COMPONENTS))
        by_name = {row["component"]: row for row in payload["component_matrix"]}
        for name in (
            "symbol_binding",
            "ev_eq_01",
            "broker_economics",
            "dataset_provenance",
            "historical_spread",
            "commission",
            "swap",
            "slippage",
            "execution",
            "cost_completeness",
        ):
            self.assertTrue(by_name[name]["blocker"])
            self.assertFalse(by_name[name]["proven"])
            self.assertNotEqual(by_name[name]["status"], COMPLETE)
        self.assertEqual(by_name["cost_model_integrity"]["status"], "ENFORCED")
        self.assertTrue(by_name["cost_model_integrity"]["proven"])
        self.assertFalse(by_name["cost_model_integrity"]["blocker"])
        self.assertEqual(by_name["historical_spread"]["evidence_grade"], "PARTIAL_CANONICAL_COVERAGE")
        self.assertEqual(by_name["commission"]["evidence_grade"], "OBSERVED_ZERO_NOT_PROVEN")
        self.assertEqual(by_name["swap"]["evidence_grade"], "CURRENT_BROKER_RATE_ONLY")
        self.assertEqual(by_name["slippage"]["evidence_grade"], "REALIZED_UNKNOWN_NOT_IDENTIFIABLE")
        self.assertEqual(by_name["execution"]["evidence_grade"], "DEAL_FILL_TAPE_ONLY")
        self.assertTrue(all(payload["upgrades_forbidden"].values()))

    def test_immutability_and_no_new_collection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2732_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])
        self.assertEqual(
            payload["canonical_fingerprint_after"],
            "ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5",
        )
        self.assertFalse(payload["production_code_changed"])
        self.assertFalse(payload["new_data_collected"])
        self.assertFalse(payload["mt5_attach_attempted"])
        self.assertFalse(payload["complete_costs_required_weakened"])
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], BLOCKED)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], BLOCKED)

    def test_artifact_schema_and_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2732_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        self.assertEqual(payload["phase"], "27.32")
        self.assertEqual(payload["status"], "PASS")
        self.assertIn("STOP after Phase 27.32", (root / PHASE2732_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot" / "backtest" / "phase27_32_final_cost_evidence_gate.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertFalse(payload["safety_confirmation"]["grades_upgraded_by_inference"])
        self.assertFalse(payload["safety_confirmation"]["phase_27_33_started"])
        self.assertEqual(payload["symbol"], "XAUUSD_i")
        self.assertEqual(payload["account_type"], "REAL")
