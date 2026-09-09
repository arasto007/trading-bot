"""Phase 27.15 — Final cost completeness gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import (
    CostAvailability,
    CostCompleteness,
    SpreadMode,
    assess_cost_completeness,
    build_backtest_cost_model,
    detect_spread_mode_from_frame,
)
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY, cost_adjusted_validation_allowed
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    PHASE2715_JSON,
    PHASE2715_MD,
    classify_dataset_row,
    cost_ready_for_validation,
    hidden_assumption_checks,
    run_phase27_15_collection,
)


def setUpModule() -> None:
    run_phase27_15_collection(Path(__file__).resolve().parents[1])


class TestPhase2715CostCompletenessGate(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.15")
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["required_inputs"]["all_present"])
        self.assertEqual(payload["operator_policy"]["treatment"], "COMPLETE_COSTS_REQUIRED")
        self.assertEqual(payload["operator_policy"]["locked_decisions"], LOCKED_POLICY)

    def test_cost_ready_remains_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["cost_ready_for_validation"])
        self.assertFalse(payload["cost_adjusted_metrics_enabled"])
        self.assertFalse(payload["profitability_validation_run"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        for name in GATE_COMPONENTS:
            self.assertNotEqual(payload["components"][name]["status"], CostCompleteness.COMPLETE.value)

    def test_one_unknown_blocks_and_all_complete_would_pass(self) -> None:
        complete = {name: {"status": CostCompleteness.COMPLETE.value} for name in GATE_COMPONENTS}
        self.assertTrue(cost_ready_for_validation(complete))
        blocked = dict(complete)
        blocked["commission"] = {"status": "UNKNOWN"}
        self.assertFalse(cost_ready_for_validation(blocked))
        blocked["commission"] = {"status": "BLOCKED"}
        self.assertFalse(cost_ready_for_validation(blocked))
        blocked["commission"] = {"status": CostCompleteness.PARTIAL.value}
        self.assertFalse(cost_ready_for_validation(blocked))
        self.assertFalse(cost_ready_for_validation({}))

    def test_complete_costs_required_enforced(self) -> None:
        self.assertFalse(cost_adjusted_validation_allowed(CostCompleteness.UNKNOWN))
        self.assertFalse(cost_adjusted_validation_allowed(CostCompleteness.PARTIAL))
        self.assertTrue(cost_adjusted_validation_allowed(CostCompleteness.COMPLETE))
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        self.assertFalse(
            compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)["cost_adjusted_metrics"]
        )
        self.assertFalse(
            compute_metrics(result, cost_completeness=CostCompleteness.PARTIAL)["cost_adjusted_metrics"]
        )
        self.assertTrue(
            compute_metrics(result, cost_completeness=CostCompleteness.COMPLETE)["cost_adjusted_metrics"]
        )

    def test_no_hidden_zero_costs(self) -> None:
        hidden = hidden_assumption_checks()
        self.assertTrue(hidden["default_commission_not_zero"])
        self.assertTrue(hidden["commission_per_lot_zero_is_not_status_zero"])
        self.assertTrue(hidden["default_swap_not_zero"])
        self.assertTrue(hidden["slippage_modeled_proxy_not_silent_zero"])
        self.assertTrue(hidden["default_slippage_not_zero"])
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)
        self.assertEqual(model.swap.availability, CostAvailability.UNKNOWN)
        self.assertNotEqual(model.slippage.availability, CostAvailability.ZERO)
        self.assertNotEqual(assess_cost_completeness(model), CostCompleteness.COMPLETE)

    def test_no_silent_symbol_mapping(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertIn(ctx.exception.code, ("SYMBOL_MISMATCH", "MISSING_MAP"))

    def test_proxy_spread_not_historical(self) -> None:
        import pandas as pd

        ohlc = pd.DataFrame({"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.0]})
        self.assertEqual(detect_spread_mode_from_frame(ohlc), SpreadMode.PROXY)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["components"]["spread"]["status"], "BLOCKED")
        self.assertTrue(payload["components"]["spread"]["proxy_is_not_historical"])
        self.assertFalse(payload["components"]["spread"]["historical_bid_ask_available"])

    def test_dataset_classes_and_zero_complete(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        counts = payload["dataset_classifications"]["counts"]
        self.assertEqual(counts["COMPLETE"], 0)
        self.assertGreater(counts["BLOCKED"], 0)
        self.assertEqual(sum(counts.values()), payload["dataset_classifications"]["total"])
        for row in payload["dataset_classifications"]["rows"]:
            self.assertIn(row["gate_class"], ("COMPLETE", "PARTIAL", "UNKNOWN", "BLOCKED"))
            if row["logical_symbol"] == "XAUUSD":
                self.assertEqual(row["gate_class"], "BLOCKED")

    def test_unbound_and_proxy_dataset_classification(self) -> None:
        unbound = classify_dataset_row(
            {
                "mapping_blocked": True,
                "mapping_status": "MISSING_MAP",
                "spread_mode": "PROXY",
                "historical_bid_ask": False,
            }
        )
        self.assertEqual(unbound, "BLOCKED")
        masquerade = classify_dataset_row(
            {
                "mapping_blocked": False,
                "mapping_status": "MATCH",
                "spread_mode": "DATASET",
                "historical_bid_ask": False,
                "commission_status": "ZERO",
                "swap_status": "ZERO",
                "slippage_status": "OBSERVED",
            }
        )
        self.assertEqual(masquerade, "BLOCKED")

    def test_blocker_matrix_covers_open_components(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        blockers = {row["blocker"]: row for row in payload["blocker_matrix"]}
        for name in GATE_COMPONENTS:
            self.assertIn(name, blockers)
            self.assertEqual(blockers[name]["severity"], "HIGH")
            self.assertIn(blockers[name]["status"], ("UNKNOWN", "PARTIAL", "BLOCKED"))
        self.assertEqual(blockers["COST_READY_FOR_VALIDATION"]["status"], "BLOCKED")
        self.assertEqual(blockers["PRODUCTION_AUTHORIZATION"]["status"], "BLOCKED")

    def test_commission_not_zero_from_observed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        comm = payload["components"]["commission"]
        self.assertEqual(comm["status"], "BLOCKED")
        self.assertFalse(comm["verified_schedule_found"])
        self.assertEqual(comm["observed_classification"], "OBSERVED_ZERO_NOT_PROVEN")

    def test_no_trading_behavior_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2715_JSON).read_text(encoding="utf-8"))
        changes = payload["changes"]
        self.assertNotIn("tradingbot/adapters/mt5_execution.py", changes)
        self.assertNotIn("tradingbot/domain/risk_logic.py", changes)
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["backtest_run"])
        self.assertFalse(safety["profitability_validation_run"])
        self.assertFalse(safety["optimization_run"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["gate_weakened"])
        self.assertFalse(safety["real_trading_enabled"])

    def test_md_and_stop(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / PHASE2715_MD).read_text(encoding="utf-8")
        self.assertIn("COST_READY_FOR_VALIDATION", text)
        self.assertIn("COMPLETE_COSTS_REQUIRED", text)
        self.assertIn("STOP after Phase 27.15", text)
        self.assertIn("Gate was **not** weakened", text)


if __name__ == "__main__":
    unittest.main()
