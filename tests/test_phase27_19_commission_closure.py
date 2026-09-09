"""Phase 27.19 — account-applicable commission schedule closure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.commission_policy import (
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    CommissionPolicyError,
    CommissionSchedule,
    accept_account_applicable_schedule,
    broker_name_match_is_not_account_verification,
    classify_observed_commissions,
    commission_per_lot_zero_is_not_explicit_zero,
    generic_public_schedule_is_account_specific,
    missing_account_applicability_fields,
    observed_zero_is_not_verified_schedule,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
)
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_19_commission_closure import (
    PHASE2719_JSON,
    PHASE2719_MD,
    public_ecn_supporting_schedule,
    run_phase27_19_collection,
)


def setUpModule() -> None:
    run_phase27_19_collection(Path(__file__).resolve().parents[1])


def _complete_account_schedule() -> CommissionSchedule:
    return CommissionSchedule(
        broker="LiteFinance Global LLC",
        server="LiteFinance-MT5-Live",
        account_type="REAL",
        account_environment="REAL",
        account_product_type="ECN",
        asset_class="gold",
        symbol="XAUUSD_i",
        basis="per_lot",
        currency="USD",
        effective_date_or_version="fixture-only",
        rate=5.0,
        applicability_established=True,
        source="account_conditions_export",
    )


class TestPhase2719CommissionClosure(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.19")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["operator_policy"]["treatment"], POLICY)
        self.assertFalse(payload["verified_schedule"]["found"])
        self.assertEqual(payload["verified_schedule"]["commission_status"], "UNKNOWN")
        self.assertEqual(payload["verified_schedule"]["status"], "BLOCKED")
        self.assertEqual(payload["verified_schedule"]["commission_status_display"], "UNKNOWN / BLOCKED")
        self.assertTrue(payload["phase27_12"]["present"])
        self.assertTrue(payload["phase27_17"]["present"])

    def test_observed_zero_is_not_verified_schedule(self) -> None:
        self.assertTrue(observed_zero_is_not_verified_schedule([0.0] * 50))
        classified = classify_observed_commissions([0.0] * 50)
        self.assertEqual(classified.status, OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(classified.proves_verified_schedule)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        tape = payload["operator_deal_tape"]
        self.assertEqual(tape["gold_deal_count"], 50)
        self.assertEqual(tape["observed_zero_count"], 50)
        self.assertEqual(tape["classification"], OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(tape["proves_verified_schedule"])
        self.assertFalse(payload["safety_confirmation"]["observed_zero_converted_to_verified"])

    def test_generic_schedule_is_not_account_specific(self) -> None:
        generic = public_ecn_supporting_schedule()
        self.assertFalse(generic_public_schedule_is_account_specific(generic))
        self.assertTrue(broker_name_match_is_not_account_verification(generic, "LiteFinance Global LLC"))
        with self.assertRaises(CommissionPolicyError) as ctx:
            accept_account_applicable_schedule(generic)
        self.assertEqual(ctx.exception.code, "GENERIC_PUBLIC_NOT_ACCOUNT_SPECIFIC")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["public_supporting_documentation"]["used_as_verified"])
        self.assertFalse(payload["public_supporting_documentation"]["used_as_account_specific"])
        self.assertFalse(payload["public_supporting_documentation"]["broker_name_match_used_as_verification"])

    def test_missing_applicability_is_not_verified(self) -> None:
        incomplete = CommissionSchedule(
            broker="LiteFinance Global LLC",
            server="LiteFinance-MT5-Live",
            account_type="REAL",
            symbol="XAUUSD_i",
            rate=5.0,
            applicability_established=False,
        )
        missing = missing_account_applicability_fields(incomplete)
        self.assertIn("account_product_type", missing)
        self.assertIn("applicability_established", missing)
        with self.assertRaises(CommissionPolicyError) as ctx:
            accept_account_applicable_schedule(incomplete)
        self.assertEqual(ctx.exception.code, "APPLICABILITY_REQUIRED")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["applicability_matrix"]["applicability_established"])
        self.assertIn("account_product_type", payload["applicability_matrix"]["missing_for_verified"])

    def test_verified_schedule_requires_complete_account_applicability(self) -> None:
        without_product = CommissionSchedule(
            broker="LiteFinance Global LLC",
            server="LiteFinance-MT5-Live",
            account_type="REAL",
            asset_class="gold",
            symbol="XAUUSD_i",
            basis="per_lot",
            currency="USD",
            effective_date_or_version="fixture-only",
            rate=5.0,
            applicability_established=True,
            source="account_conditions_export",
        )
        with self.assertRaises(CommissionPolicyError):
            accept_account_applicable_schedule(without_product)
        accepted = accept_account_applicable_schedule(_complete_account_schedule())
        self.assertEqual(accepted.source_class, POLICY)
        self.assertEqual(accepted.account_product_type, "ECN")

    def test_commission_per_lot_zero_is_not_zero_status(self) -> None:
        cfg = BacktestConfig()
        self.assertEqual(cfg.commission_per_lot, 0.0)
        self.assertEqual(cfg.commission_status, "UNKNOWN")
        self.assertTrue(commission_per_lot_zero_is_not_explicit_zero(cfg.commission_per_lot, cfg.commission_status))
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)
        self.assertNotEqual(model.commission.availability, CostAvailability.ZERO)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["default_commission_per_lot"], 0.0)
        self.assertFalse(payload["safety_confirmation"]["commission_per_lot_zero_converted_to_zero_status"])

    def test_cost_completeness_remains_fail_closed(self) -> None:
        for status in ("UNKNOWN", OBSERVED_ZERO_NOT_PROVEN, POLICY):
            model = build_backtest_cost_model(
                BacktestConfig(
                    spread_mode="PROXY",
                    commission_status=status,
                    swap_status="ZERO",
                    slippage_status="MODELED_PROXY",
                ),
                spread_mode="PROXY",
            )
            self.assertNotEqual(assess_cost_completeness(model), CostCompleteness.COMPLETE)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertEqual(payload["production_readiness"], "BLOCKED")

    def test_no_symbol_select_or_env_in_source(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_19_commission_closure.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("load_dotenv", src)
        self.assertNotIn('Path(".env")', src)
        self.assertNotIn("order_send(", src)

    def test_safety_and_md(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2719_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["commission_fabricated"])
        self.assertFalse(safety["zero_commission_assumed"])
        self.assertFalse(safety["phase_27_20_started"])
        text = (root / PHASE2719_MD).read_text(encoding="utf-8")
        self.assertIn("VERIFIED_SCHEDULE", text)
        self.assertIn("OBSERVED_ZERO_NOT_PROVEN", text)
        self.assertIn("STOP after Phase 27.19", text)
        self.assertIn("Observed zero ≠ verified schedule", text)
        self.assertIn("Generic public schedule ≠ account-specific schedule", text)


if __name__ == "__main__":
    unittest.main()
