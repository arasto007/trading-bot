"""Phase 26 — offline validation readiness audit tests (no MT5, no credentials)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase26_validation_audit import (
    PHASE26_CLAIMS_JSON,
    PHASE26_MATRIX_JSON,
    PHASE26_PARITY_JSON,
    PHASE26_READINESS_JSON,
    ActivationClass,
    BiasSeverity,
    build_strategy_inventory,
    build_validation_matrix,
    run_phase26_validation_audit,
    run_phase26_validation_collection,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion
from tradingbot.config.live import PRIMARY_SYMBOL


def _ohlc(root: Path, name: str = "XAUUSD_M5_5d.parquet") -> Path:
    bt = root / "data" / "backtest"
    bt.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": [1.0] * 10, "high": [1.1] * 10, "low": [0.9] * 10, "close": [1.0] * 10, "volume": [1.0] * 10},
        index=idx,
    )
    out = bt / name
    df.to_parquet(out)
    return out


class TestOfflineSafety(unittest.TestCase):
    def test_no_mt5_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_collection(base_dir=tmp)
        self.assertFalse(r.safety["MT5_STARTED"])
        self.assertFalse(r.safety["BOT_STARTED"])
        self.assertFalse(r.safety["ENV_ACCESSED"])
        self.assertFalse(r.safety["CREDENTIALS_ACCESSED"])
        self.assertFalse(r.safety["SYMBOL_SELECT"])
        self.assertFalse(r.safety["ORDERS_SENT"])

    def test_strategy_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_collection(base_dir=tmp)
        self.assertFalse(r.safety["STRATEGY_CHANGED"])
        self.assertFalse(r.safety["RISKGATE_CHANGED"])
        self.assertFalse(r.safety["ROUTER_CHANGED"])

    def test_artifacts_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_phase26_validation_collection(base_dir=tmp)
            root = Path(tmp)
            for name in (
                PHASE26_READINESS_JSON,
                PHASE26_CLAIMS_JSON,
                PHASE26_PARITY_JSON,
                PHASE26_MATRIX_JSON,
            ):
                self.assertTrue((root / name).is_file(), name)


class TestDeterministicOutput(unittest.TestCase):
    def test_strategy_inventory_has_pa_active(self) -> None:
        inv = build_strategy_inventory()
        active = [i for i in inv if i["item"] == "active_strategy"][0]
        self.assertEqual(active["classification"], ActivationClass.IMPLEMENTED_AND_ACTIVE.value)
        self.assertEqual(active["value"], "priceaction")

    def test_status_pass_with_deferral(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        self.assertIn(r.status, {"PASS_WITH_DEFERRAL", "PASS"})

    def test_broker_gate_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        self.assertTrue(r.broker_evidence_gate["phase_25m_final"])
        self.assertFalse(r.broker_evidence_gate["phase_25n_exists"])


class TestEvidenceNotPromoted(unittest.TestCase):
    def test_cost_adjusted_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        self.assertFalse(r.cost_model_audit["cost_adjusted_metrics_partial"])
        self.assertFalse(r.cost_model_audit["cost_adjusted_metrics_unknown"])

    def test_ev_eq_remains_not_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        self.assertEqual(r.broker_evidence_gate["ev_eq_01"], EquivalenceConclusion.NOT_PROVEN.value)

    def test_proxy_spread_in_cost_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            r = run_phase26_validation_audit(base_dir=tmp)
        spreads = {row["spread"] for row in r.dataset_realism}
        self.assertIn(SpreadMode.PROXY.value, spreads)

    def test_commission_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        self.assertEqual(r.cost_model_audit["components"]["COMMISSION"]["classification"], "UNKNOWN")

    def test_no_silent_xauusd_mapping(self) -> None:
        from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset

        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})


class TestValidationMatrix(unittest.TestCase):
    def test_matrix_internally_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            r = run_phase26_validation_audit(base_dir=tmp)
        matrix = r.validation_matrix
        self.assertGreaterEqual(len(matrix), 10)
        blocked = [m for m in matrix if m["test"] == "broker_bound_backtest"][0]
        self.assertFalse(blocked["can_run_now"])
        baseline = [m for m in matrix if m["test"] == "baseline_backtest"][0]
        self.assertTrue(baseline["can_run_now"])

    def test_readiness_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        keys = set(r.validation_readiness.keys())
        self.assertTrue(keys >= {"A_VALID_NOW", "C_NOT_VALID_UNTIL_BROKER_EVIDENCE"})


class TestImmutability(unittest.TestCase):
    def test_datasets_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            r = run_phase26_validation_collection(base_dir=tmp)
        self.assertTrue(r.immutability_ok)
        self.assertFalse(r.safety["DATASETS_MUTATED"])


class TestPerformanceClaims(unittest.TestCase):
    def test_claims_no_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_phase26_validation_collection(base_dir=tmp)
            text = (Path(tmp) / PHASE26_CLAIMS_JSON).read_text().lower()
        self.assertNotIn("password", text)


class TestBiasAudit(unittest.TestCase):
    def test_p0_issues_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_phase26_validation_audit(base_dir=tmp)
        p0_ids = {b["id"] for b in r.blockers["P0"]}
        self.assertIn("PHASE25M_OPERATOR_BLOCKED", p0_ids)

    def test_sl_before_tp_ok(self) -> None:
        checks = {c["id"]: c for c in run_phase26_validation_audit(base_dir=tempfile.mkdtemp()).backtest_bias_audit}
        self.assertEqual(checks["SL_BEFORE_TP"]["severity"], BiasSeverity.OK.value)


if __name__ == "__main__":
    unittest.main()
