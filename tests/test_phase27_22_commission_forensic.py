"""Phase 27.22 — commission and account-product forensic tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.commission_policy import (
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    UNKNOWN,
    CommissionPolicyError,
    accept_account_applicable_schedule,
    classify_observed_commissions,
    generic_public_schedule_is_account_specific,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_19_commission_closure import public_ecn_supporting_schedule
from tradingbot.backtest.phase27_22_commission_forensic import (
    PHASE2722_JSON,
    PHASE2722_MD,
    classify_commission_forensic,
    detect_product_from_identifiers,
    run_phase27_22_collection,
)


FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "Path('.env')",
)
FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")


def setUpModule() -> None:
    run_phase27_22_collection(Path(__file__).resolve().parents[1])


class TestPhase2722CommissionForensic(unittest.TestCase):
    def test_artifact_classification_is_observed_zero_not_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2722_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.22")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["classification"], OBSERVED_ZERO_NOT_PROVEN)
        self.assertNotEqual(payload["classification"], POLICY)
        self.assertFalse(payload["verified_schedule_found"])
        self.assertFalse(payload["applicability_established"])
        self.assertEqual(payload["account"]["account_product_type"], UNKNOWN)
        self.assertEqual(payload["operator_policy"]["treatment"], POLICY)

    def test_observed_zero_is_not_verified_schedule(self) -> None:
        classified = classify_observed_commissions([0.0] * 50)
        self.assertEqual(classified.status, OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(classified.proves_verified_schedule)
        self.assertEqual(
            classify_commission_forensic(
                product_type=UNKNOWN,
                applicability_established=False,
                verified_accepted=False,
                observed_zero_count=50,
                observed_nonzero_count=0,
            ),
            OBSERVED_ZERO_NOT_PROVEN,
        )
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2722_JSON).read_text(encoding="utf-8"))
        tape = payload["commission_evidence"]
        self.assertEqual(tape["gold_deal_count"], 50)
        self.assertEqual(tape["observed_zero_count"], 50)
        self.assertEqual(tape["observed_nonzero_count"], 0)
        self.assertEqual(tape["classification"], OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(tape["proves_verified_schedule"])
        self.assertFalse(tape["proves_universal_zero"])

    def test_generic_public_schedule_is_not_account_specific(self) -> None:
        generic = public_ecn_supporting_schedule()
        self.assertFalse(generic_public_schedule_is_account_specific(generic))
        with self.assertRaises(CommissionPolicyError):
            accept_account_applicable_schedule(generic)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2722_JSON).read_text(encoding="utf-8"))
        public = payload["public_supporting_documentation"]
        self.assertFalse(public["used_as_verified"])
        self.assertFalse(public["used_as_account_specific"])
        self.assertFalse(public["applicability_established"])

    def test_missing_product_is_not_verified(self) -> None:
        self.assertEqual(
            detect_product_from_identifiers({"company": "LiteFinance Global LLC", "server": "LiteFinance-MT5-Live"})[
                "account_product_type"
            ],
            UNKNOWN,
        )
        self.assertEqual(
            detect_product_from_identifiers({"commission": 0.0, "symbol": "XAUUSD_i", "balance": 1000})[
                "account_product_type"
            ],
            UNKNOWN,
        )
        self.assertEqual(
            detect_product_from_identifiers({"account_product_type": "ECN"})["account_product_type"],
            "ECN",
        )
        self.assertEqual(
            classify_commission_forensic(
                product_type=UNKNOWN,
                applicability_established=False,
                verified_accepted=False,
                observed_zero_count=50,
                observed_nonzero_count=0,
            ),
            OBSERVED_ZERO_NOT_PROVEN,
        )
        self.assertNotEqual(
            classify_commission_forensic(
                product_type=UNKNOWN,
                applicability_established=False,
                verified_accepted=False,
                observed_zero_count=50,
                observed_nonzero_count=0,
            ),
            POLICY,
        )

    def test_cost_completeness_and_final_gate_remain_blocked(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertNotEqual(assess_cost_completeness(model), CostCompleteness.COMPLETE)
        self.assertNotEqual(model.commission.availability, CostAvailability.ZERO)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2722_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertFalse(payload["complete_costs_required_weakened"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")

    def test_no_symbol_select_env_or_credentials(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_22_commission_forensic.py"
        ).read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2722_JSON).read_text(encoding="utf-8").lower()
        for key in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(f'"{key}"', raw)
        self.assertNotIn("password", raw)

    def test_safety_and_md(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2722_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["mt5_restarted"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["env_file_read"])
        self.assertFalse(safety["credentials_exposed"])
        self.assertFalse(safety["product_inferred_from_zero_commission"])
        self.assertFalse(safety["product_inferred_from_broker_name"])
        self.assertFalse(safety["product_inferred_from_balance"])
        self.assertFalse(safety["product_inferred_from_trade_history"])
        self.assertFalse(safety["zero_converted_to_zero_status"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["phase_27_23_started"])
        self.assertTrue(payload["operator_action_required"])
        text = (root / PHASE2722_MD).read_text(encoding="utf-8")
        self.assertIn("VERIFIED_SCHEDULE", text)
        self.assertIn("OBSERVED_ZERO_NOT_PROVEN", text)
        self.assertIn("account_product_type", text)
        self.assertIn("STOP after Phase 27.22", text)
        self.assertIn("COMPLETE_COSTS_REQUIRED", text)


if __name__ == "__main__":
    unittest.main()
