"""Phase 25H — operator MT5 session tests (offline; MT5 mocked)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
from tradingbot.backtest.dataset_provenance import validate_sidecar_no_credentials
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult, ticks_to_m5_bidask_bars
from tradingbot.backtest.phase25g_run import verify_bidask_backtest_loading
from tradingbot.backtest.phase25h_run import (
    FRESH_EVIDENCE_CLASS,
    build_immutability_manifest,
    run_phase25h_collection,
    verify_immutability,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion, build_equivalence_audit, SymbolSpecSnapshot
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.services.demo_account_guard import allow_real_account_trading


def _bars(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2024-06-01 12:00", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [2400.0] * n,
            "high": [2400.5] * n,
            "low": [2399.5] * n,
            "close": [2400.2] * n,
            "volume": [1.0] * n,
            "bid": [2400.0] * n,
            "ask": [2400.3] * n,
            "spread": [0.3] * n,
        },
        index=idx,
    )


def _ticks() -> pd.DataFrame:
    times = pd.date_range("2024-06-01 12:00", periods=60, freq="30s", tz="UTC")
    return pd.DataFrame(
        {
            "time": [int(t.timestamp()) for t in times],
            "bid": [2400.0 + i * 0.01 for i in range(60)],
            "ask": [2400.3 + i * 0.01 for i in range(60)],
            "last": [2400.15 + i * 0.01 for i in range(60)],
            "volume": [1] * 60,
        }
    )


class TestAttachOnlyBehavior(unittest.TestCase):
    def test_no_mt5_startup_flag(self) -> None:
        report = run_phase25h_collection.__doc__ or ""
        self.assertIn("Does NOT start MT5", report)

    def test_mt5_unavailable_deferred(self) -> None:
        with patch("tradingbot.backtest.phase25h_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25h_collection(base_dir=tmp)
        self.assertEqual(r.status, "DEFERRED")
        self.assertEqual(r.evidence_class, "DEFERRED")
        self.assertFalse(r.mt5_started_by_script)

    def test_symbol_select_not_called(self) -> None:
        with patch("tradingbot.backtest.phase25h_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25h_collection(base_dir=tmp)
        self.assertFalse(r.symbol_select_called)

    def test_no_order_submission_in_method(self) -> None:
        self.assertIn("no orders", ReadOnlyCollectionResult(ok=False).method)


class TestCredentialSafety(unittest.TestCase):
    def test_no_credentials_in_artifact(self) -> None:
        self.assertFalse(validate_sidecar_no_credentials({"login": 1, "password": "x"}))

    def test_deferred_raw_has_no_secrets(self) -> None:
        with patch("tradingbot.backtest.phase25h_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25h_collection(base_dir=tmp)
                raw = json.loads((Path(tmp) / "logs" / "phase25h_bidask_collection_raw.json").read_text())
        self.assertNotIn("password", json.dumps(raw).lower())


class TestCatalogHandling(unittest.TestCase):
    def test_xauusd_absent(self) -> None:
        left = SymbolSpecSnapshot(symbol="XAUUSD", exists=False)
        right = SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, spec={"trade_contract_size": 100.0})
        audit = build_equivalence_audit(left, right)
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_xauusd_i_present(self) -> None:
        catalog = ReadOnlyCollectionResult(
            ok=True,
            symbol_specs={"XAUUSD_i": {"exists": True, "visible": True}},
        )
        self.assertTrue(catalog.symbol_specs["XAUUSD_i"]["exists"])


class TestEquivalencePaths(unittest.TestCase):
    def test_proven_path(self) -> None:
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
        left = SymbolSpecSnapshot(symbol="XAUUSD", exists=True, spec=spec)
        right = SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, spec=spec)
        self.assertEqual(build_equivalence_audit(left, right).ev_eq_01, EquivalenceConclusion.PROVEN.value)

    def test_disproven_path(self) -> None:
        left = SymbolSpecSnapshot(
            symbol="XAUUSD",
            exists=True,
            spec={"trade_contract_size": 100.0, "point": 0.01, "digits": 2, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01},
        )
        right = SymbolSpecSnapshot(
            symbol="XAUUSD_i",
            exists=True,
            spec={"trade_contract_size": 1000.0, "point": 0.01, "digits": 2, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01},
        )
        self.assertEqual(build_equivalence_audit(left, right).ev_eq_01, EquivalenceConclusion.DISPROVEN.value)

    def test_not_proven_incomplete(self) -> None:
        left = SymbolSpecSnapshot(symbol="XAUUSD", exists=False)
        right = SymbolSpecSnapshot(symbol="XAUUSD_i", exists=True, spec={"trade_contract_size": 100.0})
        self.assertEqual(build_equivalence_audit(left, right).ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_no_silent_mapping(self) -> None:
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL)


class TestBidAskValidation(unittest.TestCase):
    def test_bid_gt_ask_rejected(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset

        df = _bars(3)
        df["ask"] = df["bid"] - 0.1
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_missing_bid(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset

        self.assertFalse(validate_bidask_dataset(_bars().drop(columns=["bid"])).ok)

    def test_missing_ask(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset

        self.assertFalse(validate_bidask_dataset(_bars().drop(columns=["ask"])).ok)

    def test_utc_provenance(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset

        v = validate_bidask_dataset(_bars())
        self.assertIn("UTC", v.timezone)


class TestSpreadClassification(unittest.TestCase):
    def test_dataset_mode(self) -> None:
        m = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=_bars())
        self.assertEqual(m.spread_mode, SpreadMode.DATASET)

    def test_ohlc_proxy_isolation(self) -> None:
        idx = pd.date_range("2024-06-01", periods=5, freq="5min")
        ohlc = pd.DataFrame(
            {"open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5, "volume": [1.0] * 5},
            index=idx,
        )
        self.assertEqual(build_backtest_cost_model(BacktestConfig(), frame=ohlc).spread_mode, SpreadMode.PROXY)


class TestCostCompleteness(unittest.TestCase):
    def test_partial_with_dataset_spread(self) -> None:
        m = build_backtest_cost_model(BacktestConfig(), frame=_bars())
        self.assertEqual(m.completeness, CostCompleteness.PARTIAL)

    def test_cost_adjusted_false(self) -> None:
        result = BacktestResult(
            config=BacktestConfig(),
            initial_balance=1000.0,
            final_balance=1000.0,
            cost_completeness=CostCompleteness.PARTIAL.value,
        )
        self.assertFalse(compute_metrics(result)["cost_adjusted_metrics"])


class TestImmutability(unittest.TestCase):
    def test_manifest_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "backtest").mkdir(parents=True)
            pq = root / "data" / "backtest" / "XAUUSD_M5.parquet"
            idx = pd.date_range("2024-01-01", periods=3, freq="5min")
            pd.DataFrame(
                {"open": [1.0] * 3, "high": [1.1] * 3, "low": [0.9] * 3, "close": [1.0] * 3, "volume": [1.0] * 3},
                index=idx,
            ).to_parquet(pq)
            before = build_immutability_manifest(root)
            ok, issues = verify_immutability(before, base_dir=root)
            self.assertTrue(ok)
            self.assertEqual(issues, [])

    def test_detect_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "backtest").mkdir(parents=True)
            pq = root / "data" / "backtest" / "XAUUSD_M5.parquet"
            idx = pd.date_range("2024-01-01", periods=3, freq="5min")
            pd.DataFrame(
                {"open": [1.0] * 3, "high": [1.1] * 3, "low": [0.9] * 3, "close": [1.0] * 3, "volume": [1.0] * 3},
                index=idx,
            ).to_parquet(pq)
            before = build_immutability_manifest(root)
            pd.DataFrame({"open": [2.0]}).to_parquet(pq)
            ok, issues = verify_immutability(before, base_dir=root)
            self.assertFalse(ok)
            self.assertTrue(any("mutated" in i for i in issues))


class TestFreshVsStale(unittest.TestCase):
    def test_deferred_marks_stale_reference(self) -> None:
        with patch("tradingbot.backtest.phase25h_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25h_collection(base_dir=tmp)
                raw = json.loads((Path(tmp) / "logs" / "phase25h_bidask_collection_raw.json").read_text())
        self.assertFalse(raw.get("fresh_live_collected"))
        self.assertIn("stale_reference", raw)

    def test_pass_marks_fresh(self) -> None:
        catalog = ReadOnlyCollectionResult(
            ok=True,
            collection_utc="2026-09-04T12:00:00+00:00",
            account_environment="DEMO",
            server="LiteFinance-MT5-Demo",
            symbol_specs={
                "XAUUSD": {"exists": False},
                "XAUUSD_i": {
                    "exists": True,
                    "spec": {
                        "trade_contract_size": 100.0,
                        "point": 0.01,
                        "digits": 2,
                        "trade_tick_size": 0.01,
                        "trade_tick_value": 1.0,
                        "volume_min": 0.01,
                        "volume_max": 100.0,
                        "volume_step": 0.01,
                        "swap_long": -89.0,
                        "swap_short": 3.0,
                    },
                },
            },
        )
        ticks = _ticks()
        with patch("tradingbot.backtest.phase25h_run.collect_readonly_symbol_catalog", return_value=catalog):
            with patch("tradingbot.backtest.phase25h_run.collect_historical_ticks", return_value=(ticks, {"ok": True, "collection_utc": "2026-09-04T12:00:00+00:00", "method": "copy_ticks_range read-only"})):
                with tempfile.TemporaryDirectory() as tmp:
                    r = run_phase25h_collection(base_dir=tmp, tick_days=1)
        self.assertEqual(r.status, "PASS")
        self.assertEqual(r.evidence_class, FRESH_EVIDENCE_CLASS)


class TestFullPipelineMock(unittest.TestCase):
    def test_backtest_loading_after_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "XAUUSD_i_M5_bidask.parquet"
            _bars().to_parquet(path, index=True)
            result = verify_bidask_backtest_loading(path)
            self.assertTrue(result["ok"])
            self.assertEqual(result["dataset_spread_mode"], SpreadMode.DATASET.value)

    def test_no_synthetic_ticks(self) -> None:
        bars = ticks_to_m5_bidask_bars(_ticks())
        self.assertFalse(bars.empty)
        self.assertTrue((bars["ask"] >= bars["bid"]).all())

    def test_real_gate(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(allow_real_account_trading())

    def test_commission_unknown_default(self) -> None:
        self.assertEqual(BacktestConfig().commission_status, "UNKNOWN")

    def test_slippage_unknown_default(self) -> None:
        self.assertEqual(BacktestConfig().slippage_status, "MODELED_PROXY")


class TestEnvironmentProvenance(unittest.TestCase):
    def test_environment_from_catalog(self) -> None:
        catalog = ReadOnlyCollectionResult(ok=True, account_environment="DEMO", server="LiteFinance-MT5-Demo")
        self.assertEqual(catalog.account_environment, "DEMO")


class TestArtifactNaming(unittest.TestCase):
    def test_phase25h_report_created_on_deferred(self) -> None:
        with patch("tradingbot.backtest.phase25h_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25h_collection(base_dir=tmp)
                self.assertTrue((Path(tmp) / "logs" / "phase25h_collection_report.json").is_file())
