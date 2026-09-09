"""Phase 27.31 — Real-account historical execution evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_15_cost_completeness_gate import evaluate_execution_model
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_31_execution_evidence import (
    GRADE_C,
    GRADE_E,
    INCOMPLETE,
    NOT_DERIVABLE,
    NOT_IDENTIFIABLE,
    NOT_OBSERVABLE,
    NOT_PROVEN,
    PHASE2724_JSON,
    PHASE2730_JSON,
    PHASE2731_JSON,
    PHASE2731_MD,
    REQUIRED_ARTIFACT_KEYS,
    UNKNOWN,
    audit_execution_tape,
    classify_execution_grade,
    classify_full_fills,
    classify_latency,
    classify_order_deal_linkage,
    classify_partial_fills,
    classify_requotes,
    price_open_is_not_requested_price,
    requested_volume,
    run_phase27_31_collection,
    simulated_broker_cannot_satisfy_complete,
    simulated_broker_is_not_realized_execution,
    zero_partials_does_not_prove_absence,
)


FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "Path('.env')",
)


def setUpModule() -> None:
    run_phase27_31_collection(Path(__file__).resolve().parents[1])


class TestPhase2731ExecutionEvidence(unittest.TestCase):
    def test_fill_volume_is_not_full_fill_or_requested_volume(self) -> None:
        self.assertEqual(
            classify_full_fills(deals_with_fill_volume=50, complete_volume_links=0, filled_order_states=0),
            NOT_PROVEN,
        )
        self.assertIsNone(requested_volume({"volume": 0.01, "price": 4414.32}, None))
        self.assertEqual(requested_volume({"requested_volume": 0.02}, None), 0.02)
        self.assertTrue(price_open_is_not_requested_price())
        audit = audit_execution_tape(
            [{"ticket": 1, "order": None, "volume": 0.01, "price": 4400.0, "time_utc": "2026-08-01T00:00:00Z"}],
            [],
        )
        self.assertEqual(audit["full_fills"], NOT_PROVEN)
        self.assertEqual(audit["order_deal_linkage"], INCOMPLETE)

    def test_zero_partials_and_missing_orders_remain_unknown(self) -> None:
        self.assertEqual(classify_partial_fills(partial_order_states=0, volume_mismatches=0), NOT_PROVEN)
        self.assertTrue(zero_partials_does_not_prove_absence(0))
        self.assertEqual(classify_requotes(requote_comments=0, orders_present=0), NOT_OBSERVABLE)
        self.assertEqual(classify_latency(paired_timestamps=0), NOT_DERIVABLE)
        self.assertEqual(classify_order_deal_linkage(deal_count=50, linked_count=0), INCOMPLETE)
        self.assertEqual(
            classify_execution_grade(deal_count=50, order_count=0, linked_count=0, lifecycle_proven=False),
            GRADE_C,
        )
        self.assertEqual(
            classify_execution_grade(deal_count=0, order_count=0, linked_count=0, lifecycle_proven=False),
            GRADE_E,
        )
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2731_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["full_fills"], NOT_PROVEN)
        self.assertEqual(payload["partial_fills"], NOT_PROVEN)
        self.assertEqual(payload["rejections"], NOT_OBSERVABLE)
        self.assertEqual(payload["canceled_orders"], NOT_OBSERVABLE)
        self.assertEqual(payload["requotes"], NOT_OBSERVABLE)
        self.assertEqual(payload["order_deal_linkage"], INCOMPLETE)
        self.assertEqual(payload["volume_linkage"], NOT_IDENTIFIABLE)
        self.assertEqual(payload["execution_latency"], NOT_DERIVABLE)
        self.assertEqual(payload["classification"], UNKNOWN)
        self.assertEqual(payload["evidence_grade"], GRADE_C)

    def test_simulated_broker_cannot_complete_or_become_realized(self) -> None:
        self.assertTrue(simulated_broker_is_not_realized_execution())
        self.assertTrue(simulated_broker_cannot_satisfy_complete())
        self.assertEqual(evaluate_execution_model()["status"], UNKNOWN)
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2731_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["simulated_broker_is_realized"])
        self.assertFalse(payload["simulated_broker_audit"]["can_satisfy_complete"])
        self.assertFalse(payload["complete_costs_satisfied"])
        self.assertFalse(payload["complete_costs_required_weakened"])
        self.assertEqual(payload["evaluate_execution_model"]["status"], UNKNOWN)

    def test_datasets_and_prior_artifacts_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2731_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])
        self.assertEqual(payload["phase27_24_fingerprint_before"], payload["phase27_24_fingerprint_after"])
        self.assertEqual(payload["phase27_30_fingerprint_before"], payload["phase27_30_fingerprint_after"])
        self.assertFalse(payload["production_code_changed"])
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertTrue((root / PHASE2724_JSON).is_file())
        self.assertTrue((root / PHASE2730_JSON).is_file())

    def test_artifact_schema_and_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2731_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        self.assertEqual(payload["phase"], "27.31")
        self.assertIn(payload["status"], {"PASS", "PASS_WITH_DEFERRAL"})
        self.assertIn("STOP after Phase 27.31", (root / PHASE2731_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot" / "backtest" / "phase27_31_execution_evidence.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertFalse(payload["safety_confirmation"]["price_open_used_as_requested"])
        self.assertFalse(payload["safety_confirmation"]["missing_states_inferred"])
        self.assertFalse(payload["safety_confirmation"]["phase_27_32_started"])
        self.assertEqual(payload["account_type"], "REAL")
        self.assertEqual(payload["broker"], "LiteFinance Global LLC")
        self.assertEqual(payload["server"], "LiteFinance-MT5-Live")
        self.assertGreaterEqual(payload.get("inspected_artifact_deal_count") or 0, 50)
