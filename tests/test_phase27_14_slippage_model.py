"""Phase 27.14 — MODELED slippage contract tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.adapters.mt5_execution import _DEVIATION
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    assess_cost_completeness,
    build_backtest_cost_model,
    estimate_round_trip_cost,
)
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase27_14_slippage_model import (
    PHASE2714_JSON,
    PHASE2714_MD,
    run_phase27_14_collection,
)
from tradingbot.backtest.slippage_policy import (
    IMPLEMENTATION_LABEL,
    POLICY,
    SlippagePolicyError,
    inflate_requested_vs_fill_to_realized_distribution,
    modeled_cannot_silently_become_zero,
    modeled_is_not_realized,
    mt5_deviation_is_realized_slippage,
    realized_samples_from_deals,
    statistically_sufficient_realized,
)


def setUpModule() -> None:
    run_phase27_14_collection(Path(__file__).resolve().parents[1])


class TestPhase2714SlippageModel(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2714_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.14")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["operator_policy"]["treatment"], POLICY)
        self.assertEqual(payload["operator_policy"]["implementation_label"], IMPLEMENTATION_LABEL)

    def test_modeled_is_not_realized(self) -> None:
        self.assertTrue(modeled_is_not_realized())
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.slippage.availability, CostAvailability.MODELED_PROXY)
        self.assertEqual(model.slippage.mode, IMPLEMENTATION_LABEL)
        self.assertNotEqual(model.slippage.mode, "REALIZED")
        self.assertNotEqual(model.slippage.availability, CostAvailability.MODELED)

    def test_no_realized_evidence_classification(self) -> None:
        samples = realized_samples_from_deals(
            [
                {"entry_price": 4414.32, "exit_price": 4414.65, "actual_fill_price": 4154.17},
                {"entry_price": 4154.17, "actual_fill_price": 4154.17},
            ]
        )
        self.assertEqual(samples, [])
        self.assertFalse(statistically_sufficient_realized(0))
        self.assertFalse(statistically_sufficient_realized(1))
        self.assertFalse(statistically_sufficient_realized(9))
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2714_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["operator_deal_tape"]["realized_sample_count"], 0)
        self.assertFalse(payload["operator_deal_tape"]["statistically_sufficient"])
        self.assertEqual(payload["operator_deal_tape"]["demo"]["slippage_class"], "UNKNOWN")
        self.assertEqual(payload["operator_deal_tape"]["real"]["slippage_class"], "UNKNOWN")
        self.assertFalse(payload["operator_deal_tape"]["real"]["entry_price_used_as_requested"])

    def test_deviation_is_not_realized_slippage(self) -> None:
        self.assertEqual(_DEVIATION, 20)
        self.assertFalse(mt5_deviation_is_realized_slippage())
        model = build_backtest_cost_model(BacktestConfig())
        self.assertNotEqual(model.slippage.source, "deviation")
        self.assertNotEqual(model.slippage.mode, "deviation")
        self.assertNotEqual(model.slippage.value, float(_DEVIATION))

    def test_requested_vs_fill_not_inflated(self) -> None:
        with self.assertRaises(SlippagePolicyError) as ctx:
            inflate_requested_vs_fill_to_realized_distribution(1)
        self.assertEqual(ctx.exception.code, "REALIZED_INFLATION_FORBIDDEN")
        claimed = build_backtest_cost_model(BacktestConfig(slippage_status="REALIZED"))
        self.assertEqual(claimed.slippage.availability, CostAvailability.UNKNOWN)
        self.assertEqual(claimed.slippage.mode, "UNKNOWN")

    def test_modeled_cannot_silently_become_zero(self) -> None:
        self.assertTrue(modeled_cannot_silently_become_zero())
        zeroish = build_backtest_cost_model(
            BacktestConfig(slippage_status="MODELED_PROXY", slippage_pips=0.0)
        )
        self.assertEqual(zeroish.slippage.availability, CostAvailability.UNKNOWN)
        self.assertIsNone(zeroish.slippage.value)

    def test_cost_completeness_blocked_by_modeled_proxy(self) -> None:
        cfg = BacktestConfig(
            spread_mode="PROXY",
            commission_status="ZERO",
            swap_status="ZERO",
            slippage_status="MODELED_PROXY",
            slippage_pips=0.8,
        )
        model = build_backtest_cost_model(cfg, spread_mode="PROXY")
        self.assertEqual(model.slippage.availability, CostAvailability.MODELED_PROXY)
        self.assertNotEqual(assess_cost_completeness(model), CostCompleteness.COMPLETE)
        self.assertNotEqual(estimate_round_trip_cost(model).completeness, CostCompleteness.COMPLETE)
        result = BacktestResult(
            config=cfg,
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        metrics = compute_metrics(result, cost_completeness=assess_cost_completeness(model))
        self.assertFalse(metrics["cost_adjusted_metrics"])

    def test_md_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / PHASE2714_MD).read_text(encoding="utf-8")
        self.assertIn("MODELED_PROXY", text)
        self.assertIn("STOP after Phase 27.14", text)
        self.assertIn("It is **not** realized slippage", text)
        payload = json.loads((root / PHASE2714_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["realized_slippage_fabricated"])
        self.assertFalse(safety["live_execution_semantics_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        self.assertFalse(payload["contract"]["mt5_deviation_is_realized"])


if __name__ == "__main__":
    unittest.main()
