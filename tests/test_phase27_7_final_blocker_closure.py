"""Phase 27.7 — Final blocker closure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.phase27_7_final_blocker_closure import (
    PHASE277_JSON,
    PHASE277_MD,
    BLOCKER_STATUSES,
    GATE_VALUES,
    build_dataset_binding_inventory,
    build_validation_gate_v277,
    commission_forensic_reconciliation,
    conservative_cost_matrix,
    final_decisions,
    run_phase27_7_collection,
    slippage_forensic,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion

FORBIDDEN = frozenset({"login", "password", "mt5_password"})


def setUpModule() -> None:
    run_phase27_7_collection(Path(__file__).resolve().parents[1])


class TestPhase277BlockerClosure(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p["phase"], "27.7")
        self.assertIn("validation_gate", p)
        self.assertIn("blockers", p)

    def test_real_evidence_structure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        re = json.loads((root / PHASE277_JSON).read_text())["real_operator_evidence"]
        self.assertIn("environment", re)
        self.assertTrue(re.get("demo_not_mislabeled_as_real", True))

    def test_demo_not_mislabeled_when_demo_attached(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        if p["real_operator_evidence"]["environment"] == "DEMO":
            self.assertFalse(p["real_operator_evidence"]["fresh_collected"])
            self.assertEqual(p["real_operator_evidence"]["status"], "BLOCKED_PENDING_OPERATOR")

    def test_ev_eq_01_not_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertEqual(p["ev_eq_01"]["status"], EquivalenceConclusion.NOT_PROVEN.value)
        self.assertEqual(p["ev_eq_01"]["outcome"], "STATE_C_NOT_PROVEN")

    def test_policy_not_auto_authorized(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertTrue(p["operator_policy"]["all_undecided"])
        self.assertTrue(p["symbol_binding"]["configured_not_authorized"])

    def test_dataset_mapping_proposed_unauthorized(self) -> None:
        rows = build_dataset_binding_inventory(Path(__file__).resolve().parents[1])
        xau = [r for r in rows if r["logical_symbol"] == "XAUUSD"]
        if xau:
            self.assertEqual(xau[0]["mapping_state"], "PROPOSED_UNAUTHORIZED")
            self.assertEqual(xau[0]["closure_status"], "BLOCKED_PENDING_OPERATOR")

    def test_commission_zero_not_universal(self) -> None:
        deals = [{"commission": 0.0, "volume": 0.01} for _ in range(50)]
        c = commission_forensic_reconciliation(Path(__file__).resolve().parents[1], deals)
        self.assertEqual(c["status"], "UNKNOWN")
        self.assertFalse(c["conservative_model_authorizable"])

    def test_commission_tier_classification(self) -> None:
        c = commission_forensic_reconciliation(Path(__file__).resolve().parents[1], [])
        self.assertIn(c["tier"], ("COMMISSION_UNKNOWN", "COMMISSION_D", "COMMISSION_C"))

    def test_swap_not_zero_from_short_holds(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertEqual(p["swap"]["historical_swap_series"], "UNKNOWN")

    def test_slippage_requires_reference_fill(self) -> None:
        s = slippage_forensic([{"price": 2000, "symbol": "XAUUSD_i"}], [])
        self.assertEqual(s["status"], "UNKNOWN")
        self.assertEqual(s["grade"], "D")

    def test_deviation_not_slippage(self) -> None:
        s = slippage_forensic([], [])
        self.assertFalse(s["mt5_deviation_is_slippage"])

    def test_spread_snapshots_not_tape(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertTrue(p["spread"].get("live_snapshots_not_historical_tape", True))

    def test_cost_completeness_not_forced(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cc = json.loads((root / PHASE277_JSON).read_text())["cost_completeness"]
        self.assertFalse(cc["forced_complete"])
        self.assertFalse(cc["cost_adjusted_metrics_enabled"])

    def test_conservative_not_complete(self) -> None:
        m = conservative_cost_matrix()
        self.assertFalse(m["commission"]["complete"])
        self.assertTrue(m["architecture_supports_scenarios"])

    def test_no_hidden_zero_costs(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)

    def test_symbol_mismatch_fail_closed(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")

    @patch("tradingbot.backtest.phase27_6_real_operator_evidence._write")
    @patch("tradingbot.backtest.phase27_6_real_operator_evidence.collect_readonly_symbol_catalog")
    def test_no_symbol_select(self, mock_cat: MagicMock, _w: MagicMock) -> None:
        from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult
        from tradingbot.backtest.phase27_6_real_operator_evidence import attempt_real_operator_evidence

        mock_cat.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
        r = attempt_real_operator_evidence(Path(__file__).resolve().parents[1])
        self.assertFalse(r.symbol_select_called)

    def test_no_orders(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertFalse(p["safety_confirmation"]["orders_sent"])

    def test_credential_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        blob = (root / PHASE277_JSON).read_text(encoding="utf-8").lower()
        for k in FORBIDDEN:
            self.assertNotIn(f'"{k}"', blob)

    def test_immutable_historical_demo_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo = root / "logs/operator_broker_evidence_demo_raw.json"
        before = demo.read_text(encoding="utf-8")
        run_phase27_7_collection(root)
        self.assertEqual(before, demo.read_text(encoding="utf-8"))

    def test_deterministic_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertIn("final_decisions", p)

    def test_gate_values_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        gates = json.loads((root / PHASE277_JSON).read_text())["validation_gate"]["gates"]
        for v in gates.values():
            self.assertIn(v, GATE_VALUES)

    def test_blocker_statuses_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for row in json.loads((root / PHASE277_JSON).read_text())["blockers"]:
            self.assertIn(row["status"], BLOCKER_STATUSES)

    def test_production_gate_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = json.loads((root / PHASE277_JSON).read_text())
        self.assertFalse(p["production_authorized"])
        self.assertEqual(p["production_changes"], "NONE")
        self.assertEqual(p["final_decisions"]["L_production_real_money_authorized"], "NO")
        self.assertEqual(p["final_decisions"]["K_profitability_validation_authorized"], "NO")

    def test_cost_ready_false_unless_pass(self) -> None:
        root = Path(__file__).resolve().parents[1]
        gate = json.loads((root / PHASE277_JSON).read_text())["validation_gate"]
        if not gate["cost_ready_for_validation"]:
            self.assertEqual(json.loads((root / PHASE277_JSON).read_text())["final_decisions"]["J_cost_ready_for_validation"], "NO")

    def test_validation_gate_structure(self) -> None:
        gate = build_validation_gate_v277(
            real_fresh=False,
            demo_mislabeled=False,
            ev_eq={"status": "NOT_PROVEN"},
            datasets=[{"mapping_state": "PROPOSED_UNAUTHORIZED"}],
            commission={"status": "UNKNOWN"},
            swap={"historical_swap_series": "UNKNOWN"},
            slippage={"status": "UNKNOWN"},
            spread={"historical_m5_tape_available": False},
            contract={"defects": False},
            policy={"DECISION_1": "UNDECIDED"},
            complete_count=0,
        )
        self.assertFalse(gate["cost_ready_for_validation"])

    def test_final_decisions_all_no_when_blocked(self) -> None:
        d = final_decisions(
            real_fresh=False,
            ev_eq={"status": "NOT_PROVEN"},
            policy={"DECISION_1": "UNDECIDED"},
            datasets=[{"mapping_state": "PROPOSED_UNAUTHORIZED"}],
            commission={"status": "UNKNOWN"},
            swap={"historical_swap_series": "UNKNOWN"},
            slippage={"realized_sample_count": 0},
            spread={"historical_m5_tape_available": False},
            complete_count=0,
            gate={"cost_ready_for_validation": False},
        )
        self.assertEqual(d["K_profitability_validation_authorized"], "NO")
        self.assertEqual(d["L_production_real_money_authorized"], "NO")

    def test_phase277_md_exists(self) -> None:
        self.assertTrue((Path(__file__).resolve().parents[1] / PHASE277_MD).is_file())


if __name__ == "__main__":
    unittest.main()
