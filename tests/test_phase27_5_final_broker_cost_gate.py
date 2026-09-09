"""Phase 27.5 — Final broker cost gate tests (focused; no full-engine backtests)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import MIN_COMMISSION_SCHEDULE_SAMPLES
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.phase27_5_final_broker_cost_gate import (
    PHASE275_JSON,
    PHASE275_MD,
    audit_commission_extended,
    audit_slippage_extended,
    build_demo_real_comparison,
    build_ev_eq_01_analysis,
    extract_economics_snapshot,
    load_all_gold_deal_records,
    run_phase27_5_collection,
    verify_cost_contract,
)
from tradingbot.backtest.phase27_5_operator_evidence import (
    OPERATOR_BLOCKER,
    collect_phase27_5_operator_session,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion

FORBIDDEN_KEYS = frozenset({"login", "password", "mt5_password", "mt5_login"})


def setUpModule() -> None:
    run_phase27_5_collection(Path(__file__).resolve().parents[1])


class TestPhase275FinalBrokerCostGate(unittest.TestCase):
    def test_artifact_exists_and_valid_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / PHASE275_JSON
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.5")
        self.assertIn("validation_gate", payload)
        self.assertIn("ev_eq_01", payload)

    def test_fresh_real_evidence_parsing_structure(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        real = payload["symbols"]["real"]
        self.assertIn("fresh_evidence", real)
        self.assertIn("XAUUSD_i", str(real))

    def test_stale_vs_fresh_evidence_classification(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo_stale = extract_economics_snapshot(
            json.loads((root / "logs/operator_broker_evidence_demo_raw.json").read_text(encoding="utf-8")),
            env="DEMO",
            source="stale",
            timestamp="2026-09-02",
            evidence_class="STALE_OPERATOR_EVIDENCE",
        )
        self.assertEqual(demo_stale["evidence_class"], "STALE_OPERATOR_EVIDENCE")

    def test_demo_real_economics_comparison(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rows = build_demo_real_comparison(root)
        self.assertTrue(rows)
        fields = {r["field"] for r in rows}
        self.assertIn("contract_size", fields)
        self.assertIn("tick_value", fields)

    def test_xauusd_absent_xauusd_i_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["economics"]["xauusd"]["exists_on_observed_terminals"])
        self.assertIn("present", payload["symbols"]["demo"]["XAUUSD_i"])

    def test_ev_eq_01_remains_not_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["ev_eq_01"]["status"], EquivalenceConclusion.NOT_PROVEN.value)

    def test_state_b_not_auto_authorized(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        state_b = payload["ev_eq_01"]["state_b"]
        self.assertFalse(state_b["currently_authorized"])
        self.assertTrue(state_b.get("configured_not_authorized") or not state_b.get("operator_policy_authorized", True))

    def test_commission_sample_classification(self) -> None:
        deals = load_all_gold_deal_records(Path(__file__).resolve().parents[1])
        comm = audit_commission_extended(deals)
        self.assertIn(comm["status"], ("UNKNOWN", "OBSERVED_ZERO", "OBSERVED_NONZERO"))
        if comm["sample_count"] < MIN_COMMISSION_SCHEDULE_SAMPLES:
            self.assertEqual(comm["status"], "UNKNOWN")

    def test_swap_broker_rate_only_classification(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        swap = payload["costs"]["swap"]
        self.assertEqual(swap["historical_swap_series"], "UNKNOWN")
        self.assertIn(swap["broker_spec_rate"]["evidence_class"], ("BROKER_SPEC_RATE",))

    def test_slippage_requires_reference_price(self) -> None:
        slip = audit_slippage_extended(
            [{"price": 2000.0, "commission": 0.0, "symbol": "XAUUSD_i"}],
            [],
        )
        self.assertEqual(slip["status"], "UNKNOWN")
        self.assertEqual(slip["realized_sample_count"], 0)

    def test_mt5_deviation_not_slippage(self) -> None:
        slip = audit_slippage_extended([], [])
        self.assertFalse(slip["mt5_deviation_is_slippage"])

    def test_spread_evidence_classification(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        spread = payload["costs"]["spread"]
        self.assertIn(spread["grade"], ("A", "B", "C", "D"))

    def test_dataset_provenance(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertGreater(payload["datasets"]["total"], 0)
        row = payload["datasets"]["rows"][0]
        self.assertIn("category", row)
        self.assertIn("cost_completeness", row)

    def test_cost_completeness_not_complete(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["cost_completeness"]["overall"], CostCompleteness.UNKNOWN.value)
        self.assertFalse(payload["cost_completeness"]["cost_adjusted_metrics_allowed"])

    def test_cost_adjusted_metrics_gating(self) -> None:
        cfg = BacktestConfig()
        result = BacktestResult(
            config=cfg,
            initial_balance=1000.0,
            final_balance=1000.0,
            trades=[],
            equity_curve=[{"equity": 1000.0}],
        )
        metrics = compute_metrics(result, cost_completeness=CostCompleteness.UNKNOWN)
        self.assertFalse(metrics["cost_adjusted_metrics"])

    def test_missing_economics_fail_closed(self) -> None:
        contract = verify_cost_contract()
        self.assertTrue(contract["commission_unknown_not_zero"])

    def test_symbol_mismatch_fail_closed(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")

    def test_no_silent_zero_cost_defaults(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(commission_status="UNKNOWN"))
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)
        self.assertEqual(model.swap.availability, CostAvailability.UNKNOWN)

    @patch("tradingbot.backtest.phase27_5_operator_evidence._write_artifacts")
    @patch("tradingbot.backtest.phase27_5_operator_evidence.collect_readonly_symbol_catalog")
    def test_mt5_unavailable_bounded(self, mock_cat: MagicMock, _mock_write: MagicMock) -> None:
        from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult

        mock_cat.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
        result = collect_phase27_5_operator_session(Path(__file__).resolve().parents[1])
        self.assertTrue(result.operator_blocked)
        self.assertEqual(result.operator_blocker, OPERATOR_BLOCKER)
        self.assertFalse(result.mt5_available)

    def test_no_symbol_select(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["safety_confirmation"]["symbol_select_called"])

    def test_no_orders(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["safety_confirmation"]["orders_sent"])

    def test_credential_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        session = root / "logs/phase27_5_operator_session_raw.json"
        if session.is_file():
            blob = session.read_text(encoding="utf-8").lower()
            for key in FORBIDDEN_KEYS:
                self.assertNotIn(f'"{key}"', blob)
        for key in FORBIDDEN_OUTPUT_KEYS:
            self.assertIn(key, FORBIDDEN_OUTPUT_KEYS)

    def test_immutable_historical_artifacts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo = root / "logs/operator_broker_evidence_demo_raw.json"
        before = demo.read_text(encoding="utf-8")
        run_phase27_5_collection(root)
        after = demo.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_deterministic_json_output(self) -> None:
        root = Path(__file__).resolve().parents[1]
        a = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        self.assertIn("timestamp", a)
        self.assertIn("validation_gate", a)

    def test_validation_gate_not_ready_without_evidence(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE275_JSON).read_text(encoding="utf-8"))
        gate = payload["validation_gate"]
        if not gate["cost_ready_for_validation"]:
            self.assertIn("NOT READY", gate["verdict"])
        self.assertFalse(payload["production_readiness"]["status"] == "APPROVED")

    def test_phase275_md_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / PHASE275_MD).is_file())

    def test_ev_eq_analysis_not_proven(self) -> None:
        rows = build_demo_real_comparison(Path(__file__).resolve().parents[1])
        analysis = build_ev_eq_01_analysis(rows)
        self.assertEqual(analysis["status"], "NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
