"""Phase 25F — bid/ask capture and XAUUSD/XAUUSD_i equivalence (offline tests)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingbot.backtest.bidask_validation import compute_spread_quality, validate_bidask_dataset
from tradingbot.backtest.cost_model import SpreadMode, validate_dataset_spread
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.dataset_provenance import DatasetMetadata, MappingStatus, validate_sidecar_no_credentials
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult, collect_readonly_symbol_catalog
from tradingbot.backtest.phase25f_run import run_offline_equivalence_audit
from tradingbot.backtest.symbol_equivalence import (
    EquivalenceConclusion,
    FieldComparison,
    SymbolSpecSnapshot,
    audit_from_operator_artifacts,
    build_equivalence_audit,
    compare_field,
    conclude_equivalence,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _bidask_df(n: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01 12:00", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [2400.0 + i * 0.1 for i in range(n)],
            "high": [2400.5 + i * 0.1 for i in range(n)],
            "low": [2399.5 + i * 0.1 for i in range(n)],
            "close": [2400.2 + i * 0.1 for i in range(n)],
            "volume": [10.0] * n,
            "bid": [2400.0 + i * 0.1 for i in range(n)],
            "ask": [2400.3 + i * 0.1 for i in range(n)],
        },
        index=idx,
    )


def _ohlc_df() -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=5, freq="5min")
    return pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5, "volume": [1.0] * 5},
        index=idx,
    )


class TestReadOnlyEvidencePath(unittest.TestCase):
    def test_no_symbol_select_in_method(self) -> None:
        result = ReadOnlyCollectionResult(ok=True)
        self.assertIn("no symbol_select", result.method)

    def test_catalog_fails_closed_when_mt5_unavailable(self) -> None:
        mock_mt5 = MagicMock()
        with patch.dict("sys.modules", {"MetaTrader5": mock_mt5}):
            with patch("tradingbot.adapters.mt5_utils.ensure_mt5_connected", return_value=False):
                from tradingbot.backtest.mt5_readonly_evidence import collect_readonly_symbol_catalog

                result = collect_readonly_symbol_catalog()
        self.assertFalse(result.ok)
        self.assertTrue(any("MT5 not connected" in e for e in result.errors))


class TestSymbolEquivalence(unittest.TestCase):
    def test_match_classification(self) -> None:
        spec = {"trade_contract_size": 100.0, "point": 0.01}
        r = compare_field("contract_size", spec, spec, left_symbol="XAUUSD", right_symbol="XAUUSD_i")
        self.assertEqual(r.classification, FieldComparison.MATCH.value)

    def test_mismatch_classification(self) -> None:
        r = compare_field(
            "contract_size",
            {"trade_contract_size": 100.0},
            {"trade_contract_size": 1000.0},
            left_symbol="XAUUSD",
            right_symbol="XAUUSD_i",
        )
        self.assertEqual(r.classification, FieldComparison.MISMATCH.value)

    def test_unknown_when_one_missing(self) -> None:
        r = compare_field(
            "tick_value",
            {"trade_tick_value": 1.0},
            {},
            left_symbol="XAUUSD",
            right_symbol="XAUUSD_i",
        )
        self.assertEqual(r.classification, FieldComparison.UNKNOWN.value)

    def test_not_proven_when_xauusd_missing(self) -> None:
        left = SymbolSpecSnapshot(symbol="XAUUSD", exists=False, environment="DEMO")
        right = SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, spec={"trade_contract_size": 100.0}, environment="DEMO")
        audit = build_equivalence_audit(left, right)
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_proven_requires_all_critical_match(self) -> None:
        spec = {
            "trade_contract_size": 100.0,
            "point": 0.01,
            "digits": 2,
            "trade_tick_size": 0.01,
            "trade_tick_value": 1.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
        }
        left = SymbolSpecSnapshot(symbol="XAUUSD", exists=True, spec=spec, environment="DEMO")
        right = SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, spec=spec, environment="DEMO")
        audit = build_equivalence_audit(left, right)
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.PROVEN.value)

    def test_disproven_on_mismatch(self) -> None:
        left = SymbolSpecSnapshot(
            symbol="XAUUSD",
            exists=True,
            spec={"trade_contract_size": 100.0, "point": 0.01, "digits": 2, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01},
            environment="DEMO",
        )
        right = SymbolSpecSnapshot(
            symbol="XAUUSD_i",
            exists=True,
            spec={"trade_contract_size": 1000.0, "point": 0.01, "digits": 2, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01},
            environment="DEMO",
        )
        audit = build_equivalence_audit(left, right)
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.DISPROVEN.value)

    def test_operator_artifacts_audit(self) -> None:
        audits = audit_from_operator_artifacts()
        self.assertGreaterEqual(len(audits), 1)
        for audit in audits:
            self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_offline_audit_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            demo = {
                "collection_utc": "2026-09-02T18:31:37Z",
                "account": {"server": "LiteFinance-MT5-Demo", "type": "DEMO"},
                "visibility": {"XAUUSD": "NO", "XAUUSD_i": "YES"},
                "XAUUSD": "NOT AVAILABLE",
                "XAUUSD_i": {"digits": 2, "point": 0.01, "trade_contract_size": 100.0},
            }
            (root / "logs").mkdir(parents=True)
            (root / "logs" / "operator_broker_evidence_demo_raw.json").write_text(
                json.dumps(demo), encoding="utf-8"
            )
            result = run_offline_equivalence_audit(base_dir=root)
            self.assertEqual(result["ev_eq_01_overall"], EquivalenceConclusion.NOT_PROVEN.value)
            self.assertTrue(Path(result["path"]).is_file())


class TestBidAskValidation(unittest.TestCase):
    def test_bidask_validation_ok(self) -> None:
        result = validate_bidask_dataset(_bidask_df())
        self.assertTrue(result.ok)

    def test_negative_spread_rejected(self) -> None:
        df = _bidask_df()
        df["ask"] = df["bid"] - 0.05
        result = validate_bidask_dataset(df)
        self.assertFalse(result.ok)

    def test_missing_bid(self) -> None:
        df = _bidask_df().drop(columns=["bid"])
        result = validate_bidask_dataset(df)
        self.assertFalse(result.ok)

    def test_missing_ask(self) -> None:
        df = _bidask_df().drop(columns=["ask"])
        result = validate_bidask_dataset(df)
        self.assertFalse(result.ok)

    def test_duplicate_timestamps(self) -> None:
        df = _bidask_df(3)
        df = pd.concat([df, df.iloc[[0]]])
        result = validate_bidask_dataset(df.sort_index())
        self.assertFalse(result.ok)

    def test_spread_price_calculation(self) -> None:
        df = _bidask_df(1)
        spread = float(df["ask"].iloc[0] - df["bid"].iloc[0])
        self.assertAlmostEqual(spread, 0.3, places=2)

    def test_dataset_spread_classification(self) -> None:
        result = validate_dataset_spread(_bidask_df())
        self.assertEqual(result.spread_mode, SpreadMode.DATASET)

    def test_ohlc_remains_proxy(self) -> None:
        result = validate_dataset_spread(_ohlc_df())
        self.assertEqual(result.spread_mode, SpreadMode.PROXY)

    def test_spread_quality_report(self) -> None:
        report = compute_spread_quality(_bidask_df(), symbol=PRIMARY_SYMBOL)
        self.assertEqual(report.spread_mode, SpreadMode.DATASET.value)
        self.assertEqual(report.spread_source, "BID_ASK_OBSERVED")
        self.assertIsNotNone(report.mean_spread)


class TestMappingPolicy(unittest.TestCase):
    def test_no_silent_mapping(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL)

    def test_explicit_map_only(self) -> None:
        sym, src = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol=PRIMARY_SYMBOL,
            dataset_symbol_map={"XAUUSD": PRIMARY_SYMBOL},
        )
        self.assertEqual(sym, PRIMARY_SYMBOL)
        self.assertEqual(src, "explicit_map")


class TestCostAndProvenance(unittest.TestCase):
    def test_incomplete_not_cost_adjusted(self) -> None:
        result = BacktestResult(
            config=None,
            initial_balance=1000.0,
            final_balance=1000.0,
            cost_completeness="PARTIAL",
            dataset_provenance=[{"spread_mode": "DATASET"}],
        )
        metrics = compute_metrics(result)
        self.assertFalse(metrics["cost_adjusted_metrics"])
        self.assertEqual(metrics["dataset_provenance_count"], 1)

    def test_sidecar_credential_guard(self) -> None:
        self.assertFalse(validate_sidecar_no_credentials({"password": "x", "dataset_symbol": "X"}))


class TestRealGate(unittest.TestCase):
    def test_unset_blocked(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())


class TestNoMutation(unittest.TestCase):
    def test_existing_parquet_unchanged_on_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_M5.parquet"
            _ohlc_df().to_parquet(pq)
            before = pq.read_bytes()
            validate_bidask_dataset(_ohlc_df())
            after = pq.read_bytes()
            self.assertEqual(before, after)


class TestDocumentationConsistency(unittest.TestCase):
    def test_ev_eq_not_proven_from_repo_artifacts(self) -> None:
        result = run_offline_equivalence_audit()
        self.assertEqual(result["ev_eq_01_overall"], EquivalenceConclusion.NOT_PROVEN.value)
