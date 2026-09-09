"""Phase 25D — dataset provenance audit and operator cost evidence (offline)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.dataset_provenance import (
    DatasetMetadata,
    EconomicsProvenance,
    MappingStatus,
    audit_backtest_datasets,
    audit_parquet_file,
    infer_symbol_from_filename,
    infer_timeframe_from_filename,
    load_dataset_metadata,
    metadata_path_for,
    save_dataset_metadata,
    write_audit_report,
)
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.operator_evidence import (
    FieldAvailability,
    SlippageEvidenceClass,
    load_operator_evidence_bundle,
    parse_closed_deal,
    summarize_commission,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _write_ohlc_parquet(path: Path, *, symbol_label: str = "XAUUSD") -> Path:
    idx = pd.date_range("2024-01-01 15:00", periods=5, freq="5min")
    df = pd.DataFrame(
        {
            "open": [2000.0] * 5,
            "high": [2001.0] * 5,
            "low": [1999.0] * 5,
            "close": [2000.5] * 5,
            "volume": [100.0] * 5,
        },
        index=idx,
    )
    out = path / f"{symbol_label}_M5_5d.parquet"
    df.to_parquet(out)
    return out


def _write_bid_ask_parquet(path: Path) -> Path:
    idx = pd.date_range("2024-01-01 15:00", periods=3, freq="5min")
    df = pd.DataFrame(
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
    out = path / "XAUUSD_i_M5_bidask.parquet"
    df.to_parquet(out)
    return out


class TestDatasetDiscovery(unittest.TestCase):
    def test_infer_xauusd_symbol(self) -> None:
        self.assertEqual(infer_symbol_from_filename("XAUUSD_M5_14d.parquet"), "XAUUSD")

    def test_infer_xauusd_i_symbol(self) -> None:
        self.assertEqual(infer_symbol_from_filename("XAUUSD_i_M5_5d.parquet"), "XAUUSD_i")

    def test_infer_timeframe(self) -> None:
        self.assertEqual(infer_timeframe_from_filename("XAUUSD_M5_14d.parquet"), "M5")

    def test_audit_repo_backtest_cache(self) -> None:
        root = Path(__file__).resolve().parents[1]
        entries = audit_backtest_datasets(base_dir=root, configured_symbol=PRIMARY_SYMBOL)
        self.assertGreater(len(entries), 0)
        names = {e.filename for e in entries}
        self.assertIn("XAUUSD_M5_14d.parquet", names)


class TestDatasetMetadataSidecar(unittest.TestCase):
    def test_sidecar_save_load(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = _write_ohlc_parquet(Path(tmp))
            meta = DatasetMetadata(
                dataset_symbol="XAUUSD",
                configured_instrument_symbol=PRIMARY_SYMBOL,
                mapping_status=MappingStatus.UNKNOWN.value,
                economics_source=EconomicsProvenance.OFFLINE_CATALOG.value,
                contract_size=100.0,
                tick_size=0.01,
                tick_value=1.0,
            )
            save_dataset_metadata(p, meta)
            self.assertTrue(metadata_path_for(p).is_file())
            loaded = load_dataset_metadata(p)
            assert loaded is not None
            self.assertEqual(loaded.dataset_symbol, "XAUUSD")
            self.assertEqual(loaded.economics_source, EconomicsProvenance.OFFLINE_CATALOG.value)


class TestSymbolMapping(unittest.TestCase):
    def test_no_silent_xauusd_equivalence(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol="XAUUSD_i")

    def test_explicit_map(self) -> None:
        broker, src = resolve_broker_symbol_for_dataset(
            "XAUUSD",
            configured_symbol="XAUUSD_i",
            dataset_symbol_map={"XAUUSD": "XAUUSD_i"},
        )
        self.assertEqual(broker, "XAUUSD_i")
        self.assertEqual(src, "explicit_map")


class TestSpreadProvenance(unittest.TestCase):
    def test_ohlc_proxy(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = _write_ohlc_parquet(Path(tmp))
            entry = audit_parquet_file(p, configured_symbol=PRIMARY_SYMBOL)
            self.assertEqual(entry.spread_mode, SpreadMode.PROXY.value)
            self.assertFalse(entry.bid_present)

    def test_bid_ask_dataset(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = _write_bid_ask_parquet(Path(tmp))
            entry = audit_parquet_file(p, configured_symbol=PRIMARY_SYMBOL)
            self.assertEqual(entry.spread_mode, SpreadMode.DATASET.value)
            self.assertTrue(entry.bid_present and entry.ask_present)


class TestOperatorEvidence(unittest.TestCase):
    def test_load_bundle_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bundle = load_operator_evidence_bundle(base_dir=root)
        self.assertFalse(bundle["credentials_exposed"])
        self.assertIn("commission", bundle)
        text = json.dumps(bundle)
        self.assertNotIn("password", text.lower())

    def test_commission_single_zero_insufficient(self) -> None:
        deal = parse_closed_deal(
            {
                "closed_deal": {
                    "symbol": "XAUUSD_i",
                    "commission": 0.0,
                    "filled_volume": 0.01,
                }
            },
            source="test",
        )
        assert deal is not None
        summary = summarize_commission([deal])
        self.assertEqual(summary.status, "UNKNOWN")
        self.assertEqual(summary.sample_count, 1)
        self.assertIn("insufficient", summary.note.lower())

    def test_slippage_unknown_without_requested(self) -> None:
        deal = parse_closed_deal(
            {
                "closed_deal": {
                    "symbol": "XAUUSD_i",
                    "entry_price": 2000.0,
                    "actual_fill_price": 2000.0,
                    "requested_volume": "NOT AVAILABLE",
                }
            },
            source="test",
        )
        assert deal is not None
        self.assertEqual(deal.slippage_class, SlippageEvidenceClass.UNKNOWN.value)

    def test_realized_slippage_when_both_prices(self) -> None:
        deal = parse_closed_deal(
            {
                "closed_deal": {
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


class TestCostCompletenessMetrics(unittest.TestCase):
    def test_incomplete_not_cost_adjusted(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000,
            final_balance=1000,
            cost_completeness="PARTIAL",
            cost_traces=[{"component": "commission", "mode": "UNKNOWN", "source": "none"}],
        )
        metrics = compute_metrics(result, cost_completeness="PARTIAL")
        self.assertFalse(metrics["cost_adjusted_metrics"])
        self.assertEqual(metrics["cost_trace_count"], 1)

    def test_commission_unknown_default(self) -> None:
        model = build_backtest_cost_model(BacktestConfig())
        self.assertEqual(model.commission.availability.value, "UNKNOWN")


class TestAuditReport(unittest.TestCase):
    def test_write_report_deterministic_shape(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = _write_ohlc_parquet(Path(tmp))
            entry = audit_parquet_file(p, configured_symbol=PRIMARY_SYMBOL)
            out = write_audit_report([entry], Path(tmp) / "audit.json")
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["dataset_count"], 1)
            self.assertIn("datasets", data)


class TestRealGate(unittest.TestCase):
    def test_unset_blocked(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())


if __name__ == "__main__":
    unittest.main()
