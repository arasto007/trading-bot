"""Phase 27.12 — VERIFIED_SCHEDULE commission evidence tests."""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from tradingbot.backtest.broker import SimulatedBroker
from tradingbot.backtest.commission_policy import (
    OBSERVED_ZERO_NOT_PROVEN,
    POLICY,
    CommissionPolicyError,
    CommissionSchedule,
    accept_verified_schedule,
    classify_observed_commissions,
    generic_public_schedule_is_account_specific,
    observed_zero_is_not_verified_schedule,
    synthesize_zero_from_observed,
    verified_schedule_requires_applicability,
)
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
    estimate_round_trip_cost,
)
from tradingbot.backtest.dataset_provenance import compute_dataset_cost_status
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase27_12_commission_evidence import (
    PHASE2712_JSON,
    PHASE2712_MD,
    run_phase27_12_collection,
)


def setUpModule() -> None:
    run_phase27_12_collection(Path(__file__).resolve().parents[1])


class TestPhase2712CommissionEvidence(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2712_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.12")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["operator_policy"]["treatment"], POLICY)
        self.assertFalse(payload["verified_schedule"]["found"])
        self.assertEqual(payload["verified_schedule"]["status"], "BLOCKED")

    def test_observed_zero_is_not_verified_schedule(self) -> None:
        self.assertTrue(observed_zero_is_not_verified_schedule([0.0]))
        self.assertTrue(observed_zero_is_not_verified_schedule([0.0] * 50))
        classified = classify_observed_commissions([0.0] * 50)
        self.assertEqual(classified.status, OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(classified.proves_verified_schedule)
        self.assertFalse(classified.proves_universal_zero)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2712_JSON).read_text(encoding="utf-8"))
        tape = payload["operator_deal_tape"]
        self.assertEqual(tape["gold_deal_count"], 50)
        self.assertEqual(tape["observed_zero_count"], 50)
        self.assertEqual(tape["classification"], OBSERVED_ZERO_NOT_PROVEN)
        self.assertFalse(tape["proves_verified_schedule"])

    def test_generic_schedule_is_not_automatically_account_specific(self) -> None:
        generic = CommissionSchedule(
            broker="LiteFinance",
            source="https://example.broker/public-commission",
            source_class="GENERIC_PUBLIC",
            public_supporting_only=True,
            rate=0.0,
        )
        self.assertFalse(generic_public_schedule_is_account_specific(generic))
        with self.assertRaises(CommissionPolicyError) as ctx:
            accept_verified_schedule(generic)
        self.assertEqual(ctx.exception.code, "GENERIC_PUBLIC_NOT_ACCOUNT_SPECIFIC")

    def test_verified_schedule_requires_applicability(self) -> None:
        incomplete = CommissionSchedule(
            broker="LiteFinance",
            server="LiteFinance-MT5-Demo",
            symbol="XAUUSD_i",
            rate=3.5,
            applicability_established=False,
        )
        self.assertFalse(verified_schedule_requires_applicability(incomplete))
        with self.assertRaises(CommissionPolicyError) as ctx:
            accept_verified_schedule(incomplete)
        self.assertEqual(ctx.exception.code, "APPLICABILITY_REQUIRED")
        complete = CommissionSchedule(
            broker="LiteFinance",
            server="LiteFinance-MT5-Live",
            account_type="REAL",
            asset_class="gold",
            symbol="XAUUSD_i",
            basis="per_lot",
            currency="USD",
            effective_date_or_version="2026-09-06",
            rate=3.5,
            applicability_established=True,
            source="account_conditions_export",
        )
        self.assertTrue(verified_schedule_requires_applicability(complete))
        accepted = accept_verified_schedule(complete)
        self.assertEqual(accepted.source_class, POLICY)

    def test_unknown_commission_blocks_complete(self) -> None:
        model = build_backtest_cost_model(
            BacktestConfig(
                spread_mode="PROXY",
                commission_status="UNKNOWN",
                swap_status="ZERO",
                slippage_status="MODELED_PROXY",
            ),
            spread_mode="PROXY",
        )
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)
        self.assertNotEqual(assess_cost_completeness(model), CostCompleteness.COMPLETE)
        dataset = compute_dataset_cost_status(
            spread_mode="DATASET",
            commission_status="UNKNOWN",
            swap_status="OBSERVED",
            slippage_status="OBSERVED",
        )
        self.assertNotEqual(dataset["cost_completeness"], CostCompleteness.COMPLETE.value)

    def test_observed_zero_and_policy_gate_block_complete(self) -> None:
        observed = build_backtest_cost_model(
            BacktestConfig(
                spread_mode="PROXY",
                commission_status=OBSERVED_ZERO_NOT_PROVEN,
                swap_status="ZERO",
                slippage_status="MODELED_PROXY",
            ),
            spread_mode="PROXY",
        )
        self.assertEqual(observed.commission.availability, CostAvailability.OBSERVED_ZERO_NOT_PROVEN)
        self.assertIsNone(observed.commission.value)
        self.assertNotEqual(assess_cost_completeness(observed), CostCompleteness.COMPLETE)

        gate = build_backtest_cost_model(
            BacktestConfig(
                spread_mode="PROXY",
                commission_status=POLICY,
                swap_status="ZERO",
                slippage_status="MODELED_PROXY",
            ),
            spread_mode="PROXY",
        )
        self.assertEqual(gate.commission.availability, CostAvailability.VERIFIED_SCHEDULE)
        self.assertIsNone(gate.commission.value)
        self.assertNotEqual(assess_cost_completeness(gate), CostCompleteness.COMPLETE)

    def test_default_commission_remains_unknown(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)
        self.assertEqual(BacktestConfig().commission_status, "UNKNOWN")
        self.assertEqual(BacktestConfig().commission_per_lot, 0.0)

    def test_cost_adjusted_blocked(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(commission_status="UNKNOWN"),
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        metrics = compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)
        self.assertFalse(metrics["cost_adjusted_metrics"])
        rt = estimate_round_trip_cost(build_backtest_cost_model(BacktestConfig()))
        self.assertNotEqual(rt.completeness, CostCompleteness.COMPLETE)

    def test_zero_not_synthesized_from_observed(self) -> None:
        with self.assertRaises(CommissionPolicyError) as ctx:
            synthesize_zero_from_observed([0.0] * 50)
        self.assertEqual(ctx.exception.code, "ZERO_FROM_OBSERVED_FORBIDDEN")

    def test_simulated_broker_fail_closed_on_unverified(self) -> None:
        source = inspect.getsource(SimulatedBroker)
        self.assertIn("commission UNKNOWN", source)
        self.assertNotIn("RiskGate", source)

    def test_no_trading_behavior_files_changed_by_phase_scope(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2712_JSON).read_text(encoding="utf-8"))
        changes = payload["changes"]
        self.assertNotIn("tradingbot/risk/risk_gate.py", changes)
        self.assertNotIn("tradingbot/adapters/mt5_execution.py", changes)
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["commission_fabricated"])
        self.assertFalse(safety["zero_commission_assumed"])

    def test_md_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / PHASE2712_MD).read_text(encoding="utf-8")
        self.assertIn("VERIFIED_SCHEDULE", text)
        self.assertIn("OBSERVED_ZERO_NOT_PROVEN", text)
        self.assertIn("STOP after Phase 27.12", text)
        self.assertIn("Observed zero ≠ verified schedule", text)
        payload = json.loads((root / PHASE2712_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        self.assertEqual(payload["deferred"], ["Phase 27.15+ — not started"])


if __name__ == "__main__":
    unittest.main()
