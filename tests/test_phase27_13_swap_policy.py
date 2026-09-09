"""Phase 27.13 — BROKER_RATE_ONLY swap policy tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.broker import SimulatedBroker
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
from tradingbot.backtest.phase27_13_swap_policy import PHASE2713_JSON, PHASE2713_MD, run_phase27_13_collection
from tradingbot.backtest.swap_policy import (
    POLICY,
    SwapPolicyError,
    broker_rate_only_is_not_historical,
    historical_swap_accrual_allowed,
    record_broker_swap_rates,
    synthesize_historical_swap_series,
    verified_zero_swap_from_realized,
    weekday_from_rollover3days,
)


def setUpModule() -> None:
    run_phase27_13_collection(Path(__file__).resolve().parents[1])


class TestPhase2713SwapPolicy(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2713_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.13")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["operator_policy"]["treatment"], POLICY)

    def test_observed_rates_are_broker_rate_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2713_JSON).read_text(encoding="utf-8"))
        demo = payload["observed_demo_rates"]
        self.assertEqual(demo["swap_long"], -89.136)
        self.assertEqual(demo["swap_short"], 3.45)
        self.assertEqual(demo["evidence_class"], POLICY)
        self.assertEqual(demo["historical_swap_series"], "UNKNOWN")

    def test_broker_rate_only_is_not_historical(self) -> None:
        rates = record_broker_swap_rates({"swap_long": -89.136, "swap_short": 3.45})
        self.assertTrue(broker_rate_only_is_not_historical(rates))
        self.assertNotEqual(rates.evidence_class, "HISTORICAL")
        self.assertEqual(rates.historical_swap_series, "UNKNOWN")

    def test_realized_zero_is_not_verified_zero(self) -> None:
        self.assertFalse(verified_zero_swap_from_realized([0.0]))
        self.assertFalse(verified_zero_swap_from_realized([0.0, 0.0]))
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2713_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["realized_deal_swap"]["zero_observed"])
        self.assertFalse(payload["realized_deal_swap"]["proves_verified_zero"])

    def test_no_historical_series_synthesized(self) -> None:
        rates = record_broker_swap_rates({"swap_long": -89.136, "swap_short": 3.45})
        with self.assertRaises(SwapPolicyError) as ctx:
            synthesize_historical_swap_series(rates, bars=100, hold_days=3)
        self.assertEqual(ctx.exception.code, "HISTORICAL_SERIES_FORBIDDEN")
        self.assertFalse(historical_swap_accrual_allowed(POLICY))
        self.assertFalse(historical_swap_accrual_allowed("UNKNOWN"))

    def test_cost_completeness_not_complete_from_broker_rates(self) -> None:
        cfg = BacktestConfig(
            spread_mode="PROXY",
            commission_status="ZERO",
            swap_status=POLICY,
            slippage_status="MODELED_PROXY",
        )
        model = build_backtest_cost_model(cfg)
        self.assertEqual(model.swap.availability, CostAvailability.BROKER_RATE_ONLY)
        self.assertIsNone(model.swap.value)
        self.assertNotEqual(assess_cost_completeness(model), CostCompleteness.COMPLETE)
        dataset = compute_dataset_cost_status(
            spread_mode="DATASET",
            commission_status="OBSERVED",
            swap_status=POLICY,
            slippage_status="OBSERVED",
        )
        self.assertNotEqual(dataset["cost_completeness"], CostCompleteness.COMPLETE.value)

    def test_cost_adjusted_blocked(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(swap_status=POLICY),
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        metrics = compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)
        self.assertFalse(metrics["cost_adjusted_metrics"])
        rt = estimate_round_trip_cost(build_backtest_cost_model(BacktestConfig(swap_status=POLICY)))
        self.assertNotEqual(rt.completeness, CostCompleteness.COMPLETE)

    def test_default_swap_remains_unknown(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.swap.availability, CostAvailability.UNKNOWN)
        self.assertEqual(BacktestConfig().swap_status, "UNKNOWN")

    def test_simulated_broker_does_not_accrue_swap(self) -> None:
        import inspect

        source = inspect.getsource(SimulatedBroker)
        self.assertNotIn("swap_long", source)
        self.assertNotIn("swap_per_lot", source)
        self.assertNotIn("accrue_swap", source)

    def test_wednesday_only_when_rollover_evidenced(self) -> None:
        self.assertEqual(weekday_from_rollover3days(3), "Wednesday")
        self.assertIsNone(weekday_from_rollover3days(None))
        rates = record_broker_swap_rates({"swap_long": -89.136, "swap_short": 3.45})
        self.assertIsNone(rates.triple_swap_weekday)
        with_day = record_broker_swap_rates(
            {"swap_long": -89.136, "swap_short": 3.45, "swap_rollover3days": 3}
        )
        self.assertEqual(with_day.triple_swap_weekday, "Wednesday")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2713_JSON).read_text(encoding="utf-8"))
        snap = payload["verified_snapshot"]
        self.assertIsNone(snap["triple_swap_weekday_demo"])
        self.assertEqual(snap["triple_swap_weekday_real"], "Wednesday")
        self.assertEqual(snap["real_swap_rollover3days"], 3)
        self.assertFalse(snap["triple_swap_supported_on_demo_snapshot"])
        self.assertTrue(snap["triple_swap_supported_on_real_snapshot"])

    def test_md_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / PHASE2713_MD).read_text(encoding="utf-8")
        self.assertIn("BROKER_RATE_ONLY", text)
        self.assertIn("STOP after Phase 27.13", text)
        payload = json.loads((root / PHASE2713_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["historical_swap_fabricated"])
        self.assertFalse(safety["rollover_schedule_invented"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
