"""Phase 27.6 — Final evidence gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.phase27_6_final_evidence_gate import (
    PHASE276_JSON,
    PHASE276_MD,
    OPERATOR_POLICY_MD,
    audit_commission_closure,
    build_dataset_reconciliation,
    build_ev_eq_01_final,
    build_operator_decisions,
    build_validation_gate,
    design_stress_model,
    run_phase27_6_collection,
    search_spread_tape_artifacts,
    verify_cost_contract_integrity,
)
from tradingbot.backtest.phase27_6_real_operator_evidence import (
    REAL_OPERATOR_BLOCKER,
    attempt_real_operator_evidence,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion

FORBIDDEN_KEYS = frozenset({"login", "password", "mt5_password"})


def setUpModule() -> None:
    run_phase27_6_collection(Path(__file__).resolve().parents[1])


class TestPhase276FinalEvidenceGate(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.6")
        self.assertIn("validation_gate", payload)

    def test_real_evidence_parsing_structure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertIn("real_evidence", payload["operator"])

    def test_stale_vs_fresh_classification(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["operator"]["demo_evidence"], ("FRESH", "STALE"))

    def test_demo_real_comparison_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["economics"]["demo_vs_real_comparison"])

    def test_xauusd_absent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["symbols"]["xauusd"]["observed_absent"])
        self.assertFalse(payload["symbols"]["xauusd"]["broker_wide_proof"])

    def test_xauusd_i_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["symbols"]["xauusd_i"]["observed_present"])

    def test_ev_eq_01_not_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["ev_eq_01"]["status"], EquivalenceConclusion.NOT_PROVEN.value)

    def test_policy_authorization_required(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["ev_eq_01"]["state_b"]["operator_policy_authorized"])
        decisions = payload["operator_decisions"]
        self.assertEqual(decisions["DECISION_1_canonical_gold_symbol"], "UNDECIDED")

    def test_dataset_mapping_blocked_policy(self) -> None:
        rows = build_dataset_reconciliation(Path(__file__).resolve().parents[1])
        xau = [r for r in rows if r["current_symbol"] == "XAUUSD"]
        if xau:
            self.assertEqual(xau[0]["required_action"], "BLOCKED_POLICY")
            self.assertFalse(xau[0]["safe_for_validation"])

    def test_commission_zero_not_universal(self) -> None:
        root = Path(__file__).resolve().parents[1]
        deals = [{"commission": 0.0, "volume": 0.01, "ticket": i} for i in range(50)]
        comm = audit_commission_closure(root, deals, [])
        self.assertEqual(comm["status"], "UNKNOWN")
        self.assertEqual(comm["nonzero_commission_count"], 0)

    def test_commission_classification(self) -> None:
        comm = audit_commission_closure(Path(__file__).resolve().parents[1], [], [])
        self.assertIn(comm["classification"], ("A", "B", "C", "D"))

    def test_swap_broker_rate_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["costs"]["swap"]["historical_swap_series"], "UNKNOWN")

    def test_short_duration_zero_swap_not_zero_series(self) -> None:
        root = Path(__file__).resolve().parents[1]
        note = payload["costs"]["swap"]["note"] if (payload := json.loads((root / PHASE276_JSON).read_text())) else ""
        self.assertIn("short", note.lower())

    def test_slippage_requires_reference_fill(self) -> None:
        from tradingbot.backtest.phase27_5_final_broker_cost_gate import audit_slippage_extended

        slip = audit_slippage_extended([{"price": 2000, "symbol": "XAUUSD_i"}], [])
        self.assertEqual(slip["status"], "UNKNOWN")

    def test_deviation_not_slippage(self) -> None:
        from tradingbot.backtest.phase27_5_final_broker_cost_gate import audit_slippage_extended

        self.assertFalse(audit_slippage_extended([], [])["mt5_deviation_is_slippage"])

    def test_spread_evidence(self) -> None:
        spread = search_spread_tape_artifacts(Path(__file__).resolve().parents[1])
        self.assertIn("historical_m5_tape_available", spread)

    def test_historical_tape_detection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertIn("historical_m5_tape_available", payload["costs"]["spread"])

    def test_cost_completeness_not_forced(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["cost_completeness"]["forced_complete"])
        self.assertEqual(payload["cost_completeness"]["status"], CostCompleteness.UNKNOWN.value)

    def test_conservative_scenario_not_enabled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["conservative_cost_scenario"]["enabled"])

    def test_stress_model_not_executed(self) -> None:
        stress = design_stress_model()
        self.assertFalse(stress["executed"])

    def test_no_hidden_zero_costs(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)

    def test_cost_adjusted_gating(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        self.assertFalse(compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)["cost_adjusted_metrics"])

    def test_symbol_mismatch_fail_closed(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")

    @patch("tradingbot.backtest.phase27_6_real_operator_evidence._write")
    @patch("tradingbot.backtest.phase27_6_real_operator_evidence.collect_readonly_symbol_catalog")
    def test_no_symbol_select(self, mock_cat: MagicMock, _w: MagicMock) -> None:
        from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult

        mock_cat.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
        r = attempt_real_operator_evidence(Path(__file__).resolve().parents[1])
        self.assertFalse(r.symbol_select_called)

    def test_no_orders(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["safety_confirmation"]["orders_sent"])

    def test_credential_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p = root / "logs/phase27_6_operator_session_raw.json"
        if p.is_file():
            blob = p.read_text(encoding="utf-8").lower()
            for k in FORBIDDEN_KEYS:
                self.assertNotIn(f'"{k}"', blob)

    def test_immutable_historical_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo = root / "logs/operator_broker_evidence_demo_raw.json"
        before = demo.read_text(encoding="utf-8")
        run_phase27_6_collection(root)
        self.assertEqual(before, demo.read_text(encoding="utf-8"))

    def test_deterministic_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        self.assertIn("timestamp", payload)
        self.assertIn("validation_gate", payload)

    def test_production_gate_blocked_unless_defensible(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE276_JSON).read_text(encoding="utf-8"))
        if not payload["validation_gate"]["cost_ready_for_validation"]:
            self.assertEqual(payload["production_readiness"]["status"], "BLOCKED")
            self.assertIn("NOT READY", payload["validation_gate"]["verdict"])

    def test_operator_policy_md_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / OPERATOR_POLICY_MD).is_file())
        text = (root / OPERATOR_POLICY_MD).read_text(encoding="utf-8")
        # Phase 27.6 template used UNDECIDED; Phase 27.8 lock retains UNDECIDED as unselected options.
        self.assertTrue("UNDECIDED" in text or "LOCKED" in text)

    def test_phase276_md_exists(self) -> None:
        self.assertTrue((Path(__file__).resolve().parents[1] / PHASE276_MD).is_file())

    def test_validation_gate_structure(self) -> None:
        gate = build_validation_gate(
            ev_eq={"status": "NOT_PROVEN"},
            economics_ok=True,
            spread={"historical_m5_tape_available": False},
            commission={"classification": "D", "status": "UNKNOWN"},
            swap={"historical_swap_series": "UNKNOWN"},
            slippage={"status": "UNKNOWN", "realized_sample_count": 0},
            datasets=[{"current_symbol": "XAUUSD", "safe_for_validation": False, "required_action": "BLOCKED_POLICY"}],
            contract={"defects": False},
            real_fresh=False,
        )
        self.assertFalse(gate["cost_ready_for_validation"])


if __name__ == "__main__":
    unittest.main()
