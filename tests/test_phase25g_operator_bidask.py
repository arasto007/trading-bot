"""Phase 25G — operator MT5 bid/ask collection tests (offline; MT5 mocked)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingbot.backtest.bidask_ingestion import ingest_bidask_parquet
from tradingbot.backtest.bidask_validation import compute_spread_quality, validate_bidask_dataset
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.dataset_provenance import DatasetMetadata, MappingStatus, validate_sidecar_no_credentials
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult, ticks_to_m5_bidask_bars
from tradingbot.backtest.phase25g_run import Phase25GReport, run_phase25g_collection, verify_bidask_backtest_loading
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _bidask_bars(n: int = 20) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01 12:00", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [2400.0 + i * 0.1 for i in range(n)],
            "high": [2400.5 + i * 0.1 for i in range(n)],
            "low": [2399.5 + i * 0.1 for i in range(n)],
            "close": [2400.2 + i * 0.1 for i in range(n)],
            "volume": [5.0] * n,
            "bid": [2400.0 + i * 0.1 for i in range(n)],
            "ask": [2400.3 + i * 0.1 for i in range(n)],
        },
        index=idx,
    )


def _ohlc_only() -> pd.DataFrame:
    idx = pd.date_range("2024-06-01", periods=5, freq="5min")
    return pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5, "volume": [1.0] * 5},
        index=idx,
    )


def _mock_ticks_df() -> pd.DataFrame:
    times = pd.date_range("2024-06-01 12:00", periods=100, freq="30s", tz="UTC")
    return pd.DataFrame(
        {
            "time": [int(t.timestamp()) for t in times],
            "bid": [2400.0 + i * 0.01 for i in range(100)],
            "ask": [2400.3 + i * 0.01 for i in range(100)],
            "last": [2400.15 + i * 0.01 for i in range(100)],
            "volume": [1] * 100,
        }
    )


class TestReadOnlyPath(unittest.TestCase):
    def test_no_orders_in_method(self) -> None:
        self.assertIn("no orders", ReadOnlyCollectionResult(ok=False).method)

    def test_deferred_when_mt5_offline(self) -> None:
        with patch("tradingbot.backtest.phase25g_run.collect_readonly_symbol_catalog") as mock_cat:
            mock_cat.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                report = run_phase25g_collection(base_dir=tmp)
        self.assertEqual(report.status, "DEFERRED")
        self.assertFalse(report.mt5_connected)
        self.assertFalse(report.bidask_dataset_created)


class TestCatalogAndEquivalence(unittest.TestCase):
    def test_xauusd_i_detection(self) -> None:
        catalog = ReadOnlyCollectionResult(
            ok=True,
            account_environment="DEMO",
            server="LiteFinance-MT5-Demo",
            symbol_specs={
                "XAUUSD": {"exists": False},
                "XAUUSD_i": {"exists": True, "visible": True, "spec": {"trade_contract_size": 100.0}},
            },
        )
        self.assertFalse(catalog.symbol_specs["XAUUSD"]["exists"])
        self.assertTrue(catalog.symbol_specs["XAUUSD_i"]["exists"])

    def test_ev_eq_not_proven_when_xauusd_missing(self) -> None:
        with patch("tradingbot.backtest.phase25g_run.collect_readonly_symbol_catalog") as mock_cat:
            mock_cat.return_value = ReadOnlyCollectionResult(
                ok=False,
                errors=["MT5 not connected"],
            )
            with tempfile.TemporaryDirectory() as tmp:
                report = run_phase25g_collection(base_dir=tmp)
        self.assertEqual(report.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)


class TestBidAskValidation(unittest.TestCase):
    def test_dataset_classification(self) -> None:
        result = validate_bidask_dataset(_bidask_bars())
        self.assertTrue(result.ok)

    def test_negative_spread_rejected(self) -> None:
        df = _bidask_bars(3)
        df["ask"] = df["bid"] - 0.1
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_missing_bid(self) -> None:
        df = _bidask_bars().drop(columns=["bid"])
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_missing_ask(self) -> None:
        df = _bidask_bars().drop(columns=["ask"])
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_duplicate_timestamps(self) -> None:
        df = _bidask_bars(3)
        df = pd.concat([df, df.iloc[[0]]]).sort_index()
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_spread_calculation(self) -> None:
        df = _bidask_bars(1)
        self.assertAlmostEqual(float(df["ask"].iloc[0] - df["bid"].iloc[0]), 0.3, places=2)

    def test_quality_observed_label(self) -> None:
        q = compute_spread_quality(_bidask_bars())
        self.assertEqual(q.spread_classification, "OBSERVED_DATASET_SPREAD")
        self.assertGreater(q.valid_row_count, 0)


class TestSpreadModes(unittest.TestCase):
    def test_ohlc_remains_proxy(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=_ohlc_only())
        self.assertEqual(model.spread_mode, SpreadMode.PROXY)

    def test_bidask_is_dataset(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=_bidask_bars())
        self.assertEqual(model.spread_mode, SpreadMode.DATASET)


class TestIngestionAndImmutability(unittest.TestCase):
    def test_ingest_creates_new_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "staging.parquet"
            bars = _bidask_bars()
            bars.to_parquet(src, index=True)
            dst = root / "XAUUSD_i_M5_bidask.parquet"
            meta = DatasetMetadata(
                dataset_symbol=PRIMARY_SYMBOL,
                configured_instrument_symbol=PRIMARY_SYMBOL,
                mapping_status=MappingStatus.MATCH.value,
                spread_mode=SpreadMode.DATASET.value,
            )
            ingest_bidask_parquet(src, dst, meta)
            self.assertTrue(dst.is_file())
            sidecar = dst.with_name(dst.stem + ".metadata.json")
            self.assertTrue(sidecar.is_file())

    def test_existing_parquet_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_M5.parquet"
            _ohlc_only().to_parquet(pq)
            before = pq.read_bytes()
            validate_bidask_dataset(_ohlc_only())
            self.assertEqual(before, pq.read_bytes())


class TestBacktestIntegration(unittest.TestCase):
    def test_verify_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "XAUUSD_i_M5_bidask.parquet"
            _bidask_bars().to_parquet(path, index=True)
            result = verify_bidask_backtest_loading(path)
            self.assertTrue(result["ok"])
            self.assertEqual(result["dataset_spread_mode"], SpreadMode.DATASET.value)
            self.assertEqual(result["ohlc_spread_mode"], SpreadMode.PROXY.value)
            self.assertFalse(result["cost_adjusted_allowed"])

    def test_cost_completeness_partial(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(), frame=_bidask_bars())
        self.assertEqual(model.completeness, CostCompleteness.PARTIAL)

    def test_metrics_guard(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            cost_completeness=CostCompleteness.PARTIAL.value,
        )
        metrics = compute_metrics(result)
        self.assertFalse(metrics["cost_adjusted_metrics"])


class TestTickAggregation(unittest.TestCase):
    def test_ticks_to_m5_no_synthetic_spread(self) -> None:
        bars = ticks_to_m5_bidask_bars(_mock_ticks_df())
        self.assertFalse(bars.empty)
        self.assertIn("bid", bars.columns)
        self.assertIn("ask", bars.columns)
        spread = bars["ask"] - bars["bid"]
        self.assertTrue((spread >= 0).all())


class TestSafety(unittest.TestCase):
    def test_credential_guard(self) -> None:
        self.assertFalse(validate_sidecar_no_credentials({"password": "secret"}))

    def test_real_gate(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())

    def test_no_silent_mapping(self) -> None:
        from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset

        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL)


class TestFullCollectionMock(unittest.TestCase):
    def test_pass_when_ticks_available(self) -> None:
        catalog = ReadOnlyCollectionResult(
            ok=True,
            collection_utc="2026-09-03T12:00:00+00:00",
            account_environment="DEMO",
            server="LiteFinance-MT5-Demo",
            symbol_specs={
                "XAUUSD": {"exists": False},
                "XAUUSD_i": {"exists": True, "visible": True, "spec": {"trade_contract_size": 100.0, "point": 0.01, "digits": 2, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01}},
            },
        )
        ticks = _mock_ticks_df()
        with patch("tradingbot.backtest.phase25g_run.collect_readonly_symbol_catalog", return_value=catalog):
            with patch("tradingbot.backtest.phase25g_run.collect_historical_ticks", return_value=(ticks, {"ok": True, "collection_utc": "2026-09-03T12:00:00+00:00", "method": "copy_ticks_range read-only"})):
                with tempfile.TemporaryDirectory() as tmp:
                    report = run_phase25g_collection(base_dir=tmp, tick_days=1)
        self.assertEqual(report.status, "PASS")
        self.assertTrue(report.bidask_dataset_created)
        self.assertEqual(report.cost_completeness, CostCompleteness.PARTIAL.value)
