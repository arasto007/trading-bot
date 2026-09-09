"""Phase 25E — sidecar deployment, bid/ask validation, backtest integration (offline)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.bidask_ingestion import BidAskIngestionError, ingest_bidask_parquet, validate_bidask_frame
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, validate_dataset_spread
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    EconomicsProvenance,
    MappingStatus,
    SidecarValidationError,
    apply_sidecar_to_backtest_config,
    audit_parquet_file,
    build_sidecar_for_parquet,
    deploy_defensible_sidecars,
    load_dataset_metadata,
    metadata_path_for,
    observed_litefinance_xauusd_i_economics,
    save_dataset_metadata,
    search_historical_bid_ask,
    sidecar_economics_override,
    validate_sidecar_against_parquet,
    validate_sidecar_no_credentials,
    validate_sidecar_schema,
)
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import SlippageEvidenceClass, parse_closed_deal
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _ohlc_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 15:00", periods=n, freq="5min")
    return pd.DataFrame(
        {
            "open": [2000.0] * n,
            "high": [2001.0] * n,
            "low": [1999.0] * n,
            "close": [2000.5] * n,
            "volume": [100.0] * n,
        },
        index=idx,
    )


def _bidask_df() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01 15:00", periods=3, freq="5min")
    return pd.DataFrame(
        {
            "open": [2000.0, 2000.0, 2000.0],
            "high": [2001.0, 2001.0, 2001.0],
            "low": [1999.0, 1999.0, 1999.0],
            "close": [2000.0, 2000.0, 2000.0],
            "volume": [1.0, 1.0, 1.0],
            "bid": [1999.85, 1999.86, 1999.87],
            "ask": [2000.15, 2000.16, 2000.17],
        },
        index=idx,
    )


class TestSidecarSchema(unittest.TestCase):
    def test_sidecar_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pq = root / "XAUUSD_i_M5.parquet"
            _ohlc_df().to_parquet(pq)
            meta = build_sidecar_for_parquet(pq)
            save_dataset_metadata(pq, meta)
            loaded = load_dataset_metadata(pq)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.dataset_symbol, "XAUUSD_i")
            self.assertEqual(loaded.economics_source, EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value)

    def test_missing_sidecar_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_M5.parquet"
            _ohlc_df().to_parquet(pq)
            self.assertIsNone(load_dataset_metadata(pq))

    def test_malformed_sidecar_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_i_M5.parquet"
            _ohlc_df().to_parquet(pq)
            bad = metadata_path_for(pq)
            bad.write_text('{"schema_version": 99}', encoding="utf-8")
            with self.assertRaises(SidecarValidationError):
                load_dataset_metadata(pq)

    def test_no_credential_fields(self) -> None:
        payload = {"schema_version": 1, "dataset_symbol": "XAUUSD_i", "password": "secret"}
        self.assertFalse(validate_sidecar_no_credentials(payload))

    def test_schema_validation(self) -> None:
        ok, _ = validate_sidecar_schema({"schema_version": 1, "dataset_symbol": "XAUUSD_i"})
        self.assertTrue(ok)


class TestSymbolMapping(unittest.TestCase):
    def test_xauusd_mapping_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_M5.parquet"
            _ohlc_df().to_parquet(pq)
            meta = build_sidecar_for_parquet(pq)
            self.assertEqual(meta.mapping_status, MappingStatus.UNKNOWN.value)
            self.assertEqual(meta.symbol_equivalence, "NOT_PROVEN")
            self.assertEqual(meta.economics_source, EconomicsProvenance.UNKNOWN.value)

    def test_xauusd_i_matching_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_i_M5.parquet"
            _ohlc_df().to_parquet(pq)
            meta = build_sidecar_for_parquet(pq)
            self.assertEqual(meta.mapping_status, MappingStatus.MATCH.value)
            self.assertEqual(meta.contract_size, 100.0)

    def test_no_silent_equivalence(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL)

    def test_ev_eq_01_not_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_H4.parquet"
            _ohlc_df().to_parquet(pq)
            meta = build_sidecar_for_parquet(pq)
            self.assertEqual(meta.symbol_equivalence, "NOT_PROVEN")


class TestEconomicsProvenance(unittest.TestCase):
    def test_observed_economics(self) -> None:
        econ = observed_litefinance_xauusd_i_economics()
        self.assertEqual(econ["contract_size"], 100.0)
        self.assertEqual(econ["tick_value"], 1.0)

    def test_unknown_economics_on_xauusd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq = Path(tmp) / "XAUUSD_M5.parquet"
            _ohlc_df().to_parquet(pq)
            meta = build_sidecar_for_parquet(pq)
            self.assertIsNone(meta.contract_size)

    def test_sidecar_override_only_for_xauusd_i(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pq_i = Path(tmp) / "XAUUSD_i_M5.parquet"
            _ohlc_df().to_parquet(pq_i)
            meta_i = build_sidecar_for_parquet(pq_i)
            self.assertIsNotNone(sidecar_economics_override(meta_i))
            pq_x = Path(tmp) / "XAUUSD_M5.parquet"
            _ohlc_df().to_parquet(pq_x)
            meta_x = build_sidecar_for_parquet(pq_x)
            self.assertIsNone(sidecar_economics_override(meta_x))


class TestSpreadValidation(unittest.TestCase):
    def test_bid_ask_detection(self) -> None:
        result = validate_dataset_spread(_bidask_df())
        self.assertEqual(result.spread_mode, SpreadMode.DATASET)
        self.assertAlmostEqual(result.mean_spread_price or 0, 0.30, places=2)

    def test_ohlc_proxy(self) -> None:
        result = validate_dataset_spread(_ohlc_df())
        self.assertEqual(result.spread_mode, SpreadMode.PROXY)

    def test_invalid_negative_spread(self) -> None:
        df = _bidask_df()
        df["ask"] = df["bid"] - 0.1
        result = validate_dataset_spread(df)
        self.assertEqual(result.spread_mode, SpreadMode.UNKNOWN)
        self.assertTrue(result.errors)

    def test_missing_bid(self) -> None:
        df = _bidask_df().drop(columns=["bid"])
        result = validate_dataset_spread(df)
        self.assertEqual(result.spread_mode, SpreadMode.UNKNOWN)

    def test_missing_ask(self) -> None:
        df = _bidask_df().drop(columns=["ask"])
        result = validate_dataset_spread(df)
        self.assertEqual(result.spread_mode, SpreadMode.UNKNOWN)

    def test_no_synthetic_spread_from_ohlc(self) -> None:
        df = _ohlc_df()
        df["high"] = df["low"] + 5.0
        result = validate_dataset_spread(df)
        self.assertEqual(result.spread_mode, SpreadMode.PROXY)


class TestSlippageEvidence(unittest.TestCase):
    def test_requires_explicit_requested_price(self) -> None:
        deal = parse_closed_deal(
            {
                "closed_deal": {
                    "symbol": "XAUUSD_i",
                    "entry_price": 4154.17,
                    "actual_fill_price": 4154.17,
                }
            },
            source="test",
        )
        assert deal is not None
        self.assertEqual(deal.slippage_class, SlippageEvidenceClass.UNKNOWN.value)
        self.assertIsNone(deal.realized_slippage)

    def test_realized_when_both_explicit(self) -> None:
        deal = parse_closed_deal(
            {
                "closed_deal": {
                    "symbol": "XAUUSD_i",
                    "requested_price": 2000.0,
                    "actual_fill_price": 2000.05,
                }
            },
            source="test",
        )
        assert deal is not None
        self.assertEqual(deal.slippage_class, SlippageEvidenceClass.REALIZED.value)
        assert deal.realized_slippage is not None
        self.assertAlmostEqual(float(deal.realized_slippage.value), 0.05)

    def test_deviation_not_slippage(self) -> None:
        from tradingbot.adapters.mt5_execution import _DEVIATION

        self.assertEqual(_DEVIATION, 20)


class TestCostCompleteness(unittest.TestCase):
    def test_commission_unknown_default(self) -> None:
        cfg = BacktestConfig()
        self.assertEqual(cfg.commission_status, "UNKNOWN")

    def test_incomplete_not_cost_adjusted(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            cost_completeness=CostCompleteness.PARTIAL.value,
        )
        metrics = compute_metrics(result)
        self.assertFalse(metrics["cost_adjusted_metrics"])


class TestSidecarValidation(unittest.TestCase):
    def test_symbol_mismatch_fails_closed(self) -> None:
        df = _ohlc_df()
        meta = DatasetMetadata(dataset_symbol="EURUSD", spread_mode=SpreadMode.PROXY.value)
        ok, reason = validate_sidecar_against_parquet(meta, df, "XAUUSD_M5.parquet")
        self.assertFalse(ok)
        self.assertIn("mismatch", reason)

    def test_economics_mismatch_sidecar_claims_dataset_without_bidask(self) -> None:
        df = _ohlc_df()
        meta = DatasetMetadata(dataset_symbol="XAUUSD_i", spread_mode=SpreadMode.DATASET.value)
        ok, reason = validate_sidecar_against_parquet(meta, df, "XAUUSD_i_M5.parquet")
        self.assertFalse(ok)


class TestBidAskIngestion(unittest.TestCase):
    def test_ingest_bidask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.parquet"
            _bidask_df().to_parquet(src)
            dst = root / "XAUUSD_i_M5_bidask.parquet"
            meta = build_sidecar_for_parquet(src)
            meta.dataset_symbol = "XAUUSD_i"
            meta.spread_mode = SpreadMode.DATASET.value
            out = ingest_bidask_parquet(src, dst, meta)
            self.assertTrue(out.is_file())
            loaded = load_dataset_metadata(out)
            assert loaded is not None
            self.assertTrue(loaded.historical_bid_ask_available)

    def test_reject_ohlc_only_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source.parquet"
            _ohlc_df().to_parquet(src)
            meta = DatasetMetadata(dataset_symbol="XAUUSD_i")
            with self.assertRaises(BidAskIngestionError):
                ingest_bidask_parquet(src, Path(tmp) / "dst.parquet", meta)


class TestBacktestIntegration(unittest.TestCase):
    def test_apply_sidecar_to_config(self) -> None:
        cfg = BacktestConfig()
        meta = DatasetMetadata(
            dataset_symbol="XAUUSD_i",
            configured_instrument_symbol=PRIMARY_SYMBOL,
            mapping_status=MappingStatus.MATCH.value,
            economics_source=EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
            contract_size=100.0,
            tick_size=0.01,
            tick_value=1.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )
        apply_sidecar_to_backtest_config(cfg, meta)
        self.assertIn(PRIMARY_SYMBOL, cfg.broker_economics or {})

    def test_provenance_in_metrics(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            dataset_provenance=[{"dataset_symbol": "XAUUSD_i", "economics_source": "OBSERVED_BROKER_EVIDENCE"}],
        )
        metrics = compute_metrics(result)
        self.assertEqual(metrics["dataset_provenance_count"], 1)


class TestRealGate(unittest.TestCase):
    def test_unset_blocked(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())


class TestNoMutation(unittest.TestCase):
    def test_deploy_does_not_modify_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pq = root / "XAUUSD_i_M5.parquet"
            _ohlc_df().to_parquet(pq)
            before = pq.read_bytes()
            meta = build_sidecar_for_parquet(pq)
            save_dataset_metadata(pq, meta)
            after = pq.read_bytes()
            self.assertEqual(before, after)


class TestHistoricalBidAskSearch(unittest.TestCase):
    def test_repo_search(self) -> None:
        result = search_historical_bid_ask()
        self.assertIn("historical_bid_ask_available", result)
        self.assertGreaterEqual(result["dataset_count"], 32)
        self.assertEqual(result["bidask_dataset_count"], 0)


class TestDeploySidecars(unittest.TestCase):
    def test_deploy_in_temp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "backtest").mkdir(parents=True)
            pq = root / "data" / "backtest" / "XAUUSD_i_M5.parquet"
            _ohlc_df().to_parquet(pq)
            report = deploy_defensible_sidecars(base_dir=root)
            self.assertEqual(report["created_count"], 1)
            self.assertTrue(metadata_path_for(pq).is_file())
