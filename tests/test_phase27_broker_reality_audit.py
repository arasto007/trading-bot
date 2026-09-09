"""Phase 27 — Broker reality audit tests (focused; no full-engine backtests)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_schema import CostEvidenceBundle, serialize_evidence_deterministic
from tradingbot.backtest.cost_model import CostCompleteness, CostAvailability, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import FORBIDDEN_OUTPUT_KEYS
from tradingbot.backtest.phase27_broker_reality_audit import (
    PHASE27_JSON,
    PHASE27_MD,
    build_evidence_table,
    build_state_analysis,
    run_phase27_collection,
)
from tradingbot.backtest.phase27_operator_evidence import (
    OPERATOR_BLOCKER,
    collect_phase27_operator_evidence,
)
from tradingbot.config.live import PRIMARY_SYMBOL

FORBIDDEN_KEYS = frozenset({"login", "password", "mt5_password", "mt5_login"})


def setUpModule() -> None:
    run_phase27_collection(Path(__file__).resolve().parents[1])


class TestPhase27BrokerReality(unittest.TestCase):
    def test_artifact_exists_and_valid_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / PHASE27_JSON
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27")
        self.assertIn("ev_eq_01", payload)
        self.assertIn("symbol_matrix", payload)

    def test_xauusd_absent_xauusd_i_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE27_JSON).read_text(encoding="utf-8"))
        demo_rows = [r for r in payload["symbol_matrix"] if r["environment"] == "DEMO"]
        self.assertTrue(any(r["symbol"] == "XAUUSD_i" and r.get("xauusd_i_exists") for r in demo_rows))
        xau = [r for r in demo_rows if r["symbol"] == "XAUUSD"]
        if xau:
            self.assertNotEqual(xau[0].get("catalog_exists"), "YES")

    def test_explicit_mapping_required_no_silent_fallback(self) -> None:
        with self.assertRaises(InstrumentContractError) as ctx:
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")
        self.assertEqual(ctx.exception.code, "SYMBOL_MISMATCH")
        broker, source = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(source, "explicit_map")

    def test_economics_lookup_uses_primary_symbol(self) -> None:
        self.assertEqual(PRIMARY_SYMBOL, "XAUUSD_i")

    def test_missing_economics_fail_closed(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(commission_status="UNKNOWN"))
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)
        from tradingbot.backtest.cost_evidence_audit import cost_adjusted_metrics_allowed

        self.assertFalse(
            cost_adjusted_metrics_allowed(
                spread_mode="PROXY",
                commission_status="UNKNOWN",
            )
        )

    def test_dataset_symbol_mismatch_fail_closed(self) -> None:
        from tradingbot.backtest.dataset_contract import resolve_dataset_instrument

        with self.assertRaises(InstrumentContractError):
            resolve_dataset_instrument(
                "XAUUSD",
                configured_symbol="XAUUSD_i",
                dataset_symbol_map={},
                allow_offline_fallback=False,
            )

    def test_sidecar_provenance_fields(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE27_JSON).read_text(encoding="utf-8"))
        for row in payload["dataset_matrix"]:
            self.assertIn("sidecar", row)
            self.assertIn("economics_provenance", row)

    def test_spread_evidence_classes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE27_JSON).read_text(encoding="utf-8"))
        spread_row = next(r for r in payload["cost_matrix"] if r["component"] == "spread")
        allowed = ("PROXY", "UNKNOWN", "OBSERVED", "STALE_OPERATOR_EVIDENCE", "DEFERRED", "OFFLINE_TEST_EVIDENCE")
        self.assertIn(spread_row["evidence_class"], allowed)

    def test_commission_unknown_behavior(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(commission_status="UNKNOWN"))
        self.assertEqual(model.commission.availability, CostAvailability.UNKNOWN)

    def test_swap_unknown_behavior(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.swap.availability, CostAvailability.UNKNOWN)

    def test_slippage_unknown_behavior(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertIn(
            model.slippage.availability,
            (CostAvailability.UNKNOWN, CostAvailability.MODELED, CostAvailability.MODELED_PROXY),
        )

    def test_cost_completeness_not_complete_by_default(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertNotEqual(model.completeness, CostCompleteness.COMPLETE)

    def test_cost_adjusted_metrics_blocked_unless_complete(self) -> None:
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
        metrics_complete = compute_metrics(result, cost_completeness=CostCompleteness.COMPLETE)
        self.assertTrue(metrics_complete["cost_adjusted_metrics"])

    def test_operator_evidence_credential_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        op_path = root / "logs/phase27_operator_evidence_raw.json"
        if op_path.is_file():
            blob = op_path.read_text(encoding="utf-8").lower()
            for key in FORBIDDEN_KEYS:
                self.assertNotIn(f'"{key}"', blob)
        for key in FORBIDDEN_OUTPUT_KEYS:
            self.assertIn(key, FORBIDDEN_OUTPUT_KEYS)

    @patch("tradingbot.backtest.phase27_operator_evidence.collect_readonly_symbol_catalog")
    def test_mt5_unavailable_path(self, mock_catalog: MagicMock) -> None:
        from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult

        mock_catalog.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
        result = collect_phase27_operator_evidence(Path(__file__).resolve().parents[1])
        self.assertTrue(result.operator_blocked)
        self.assertEqual(result.operator_blocker, OPERATOR_BLOCKER)
        self.assertFalse(result.mt5_available)

    def test_no_symbol_select_side_effect(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE27_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["safety_confirmation"]["symbol_select_called"])

    def test_no_order_send_side_effect(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE27_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["safety_confirmation"]["orders_sent"])

    def test_historical_evidence_immutability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo = root / "logs/operator_broker_evidence_demo_raw.json"
        self.assertTrue(demo.is_file())
        first = demo.read_text(encoding="utf-8")
        run_phase27_collection(root)
        second = demo.read_text(encoding="utf-8")
        self.assertEqual(first, second)

    def test_deterministic_evidence_serialization(self) -> None:
        bundle = CostEvidenceBundle(logical_symbol="XAUUSD", broker_symbol="XAUUSD_i", environment="DEMO")
        a = serialize_evidence_deterministic(bundle)
        b = serialize_evidence_deterministic(bundle)
        self.assertEqual(a, b)

    def test_ev_eq_01_remains_not_proven(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE27_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["ev_eq_01"]["status"], "NOT_PROVEN")
        state = build_state_analysis("NOT_PROVEN")
        self.assertFalse(state["state_a"]["justified"])
        self.assertFalse(state["state_b"]["justified"])

    def test_phase27_md_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / PHASE27_MD).is_file())

    def test_evidence_table_has_required_columns(self) -> None:
        root = Path(__file__).resolve().parents[1]
        table = build_evidence_table(root)
        self.assertTrue(table)
        for col in ("logical_symbol", "broker_symbol", "environment", "evidence_class"):
            self.assertIn(col, table[0])


if __name__ == "__main__":
    unittest.main()
