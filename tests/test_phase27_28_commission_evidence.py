"""Phase 27.28 — Real-account commission evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.commission_policy import (
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    UNKNOWN,
    classify_observed_commissions,
    generic_public_schedule_is_account_specific,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_19_commission_closure import public_ecn_supporting_schedule
from tradingbot.backtest.phase27_28_commission_evidence import (
    FINAL_A,
    FINAL_C,
    GRADE_A,
    GRADE_C,
    GRADE_D,
    PHASE2728_JSON,
    PHASE2728_MD,
    REQUIRED_ARTIFACT_KEYS,
    classify_evidence_grade,
    classify_public_source,
    run_phase27_28_collection,
    schedule_satisfies_verified_policy,
)


FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
COMPLETE_SCHEDULE = {
    "broker": "LiteFinance Global LLC",
    "server": "LiteFinance-MT5-Live",
    "account_type": "REAL",
    "account_product_type": "ECN",
    "asset_class": "gold",
    "symbol": "XAUUSD_i",
    "basis": "per_lot",
    "currency": "USD",
    "effective_date_or_version": "2026-09-06",
    "rate": 5.0,
    "applicability_established": True,
    "public_supporting_only": False,
}


def setUpModule() -> None:
    run_phase27_28_collection(Path(__file__).resolve().parents[1])


class TestPhase2728CommissionEvidence(unittest.TestCase):
    def test_zero_commission_is_not_verified_schedule(self) -> None:
        observed = classify_observed_commissions([0.0] * 50)
        self.assertEqual(observed.status, OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(observed.proves_verified_schedule)
        self.assertEqual(
            classify_evidence_grade(
                product_type=UNKNOWN,
                verified_accepted=False,
                applicability_established=False,
                product_schedule_linked=False,
                observed_zero_count=50,
                observed_nonzero_count=0,
            ),
            GRADE_C,
        )
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2728_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["evidence_grade"], GRADE_C)
        self.assertEqual(payload["final_classification"], FINAL_C)
        self.assertFalse(payload["verified_schedule_satisfied"])
        self.assertNotEqual(payload["final_classification"], POLICY)
        self.assertNotEqual(payload["final_classification"], FINAL_A)

    def test_missing_account_product_remains_unknown(self) -> None:
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2728_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["account_product_type"], UNKNOWN)
        self.assertFalse(payload["account_product"]["inferred_from_zero_commission"])
        self.assertFalse(payload["safety_confirmation"]["product_inferred"])

    def test_generic_broker_schedule_is_not_account_specific(self) -> None:
        self.assertFalse(generic_public_schedule_is_account_specific(public_ecn_supporting_schedule()))
        self.assertEqual(
            classify_public_source({"role": "supporting_only", "applies_to_this_account": False}),
            "GENERIC_SUPPORTING",
        )
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2728_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["schedule_class"], "GENERIC_SUPPORTING")
        self.assertFalse(payload["safety_confirmation"]["public_page_used_as_account_proof"])
        for doc in payload["public_supporting_documentation"]:
            self.assertFalse(doc["account_specific"])
            self.assertEqual(doc["source_class"], "GENERIC_SUPPORTING")

    def test_complete_schedule_can_satisfy_verified_and_incomplete_cannot(self) -> None:
        self.assertTrue(schedule_satisfies_verified_policy(COMPLETE_SCHEDULE))
        self.assertEqual(
            classify_evidence_grade(
                product_type="ECN",
                verified_accepted=True,
                applicability_established=True,
                product_schedule_linked=True,
                observed_zero_count=50,
                observed_nonzero_count=0,
            ),
            GRADE_A,
        )
        incomplete = dict(COMPLETE_SCHEDULE)
        incomplete["account_product_type"] = UNKNOWN
        incomplete["applicability_established"] = False
        incomplete["effective_date_or_version"] = UNKNOWN
        self.assertFalse(schedule_satisfies_verified_policy(incomplete))
        self.assertEqual(
            classify_evidence_grade(
                product_type=UNKNOWN,
                verified_accepted=False,
                applicability_established=False,
                product_schedule_linked=False,
                observed_zero_count=0,
                observed_nonzero_count=0,
            ),
            GRADE_D,
        )

    def test_unknown_commission_blocks_complete(self) -> None:
        from tradingbot.backtest.commission_policy import (
            cost_completeness_from_observed_zero_status,
            cost_completeness_from_unknown_commission,
        )

        self.assertNotEqual(cost_completeness_from_unknown_commission(), CostCompleteness.COMPLETE)
        self.assertNotEqual(cost_completeness_from_observed_zero_status(), CostCompleteness.COMPLETE)
        self.assertEqual(BacktestConfig().commission_status, UNKNOWN)
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2728_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["implementation_audit"]["unknown_blocks_complete"])
        self.assertTrue(payload["implementation_audit"]["observed_zero_blocks_complete"])
        self.assertFalse(payload["implementation_audit"]["observed_zero_becomes_zero"])
        self.assertTrue(payload["implementation_audit"]["unknown_fail_closed"])

    def test_datasets_and_gate_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2728_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["datasets_changed"])
        self.assertTrue(payload["original_datasets_untouched"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])
        self.assertFalse(payload["production_code_changed"])
        self.assertFalse(payload["complete_costs_required_weakened"])
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")

    def test_artifact_schema_and_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2728_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        self.assertEqual(payload["phase"], "27.28")
        self.assertIn("STOP after Phase 27.28", (root / PHASE2728_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot" / "backtest" / "commission_policy.py").read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("order_send(", src)
        self.assertNotIn("load_dotenv", src)
