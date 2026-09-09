"""Phase 25J — cost evidence closure tests (offline; MT5 mocked)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import ReportEvidenceClass, audit_commission_evidence
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import EconomicsProvenance, validate_sidecar_no_credentials
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult, ticks_to_m5_bidask_bars
from tradingbot.backtest.operator_evidence import SlippageEvidenceClass, SwapEvidenceClass, parse_closed_deal, summarize_commission
from tradingbot.backtest.phase25h_run import FRESH_EVIDENCE_CLASS, build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase25j_run import (
    PHASE25J_AUDIT_JSON,
    PHASE25J_REPORT_MD,
    build_dataset_cost_matrix,
    render_phase25j_report_md,
    run_phase25j_closure_audit,
    run_phase25j_collection,
    run_phase25j_mt5_collection,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion, build_equivalence_audit, SymbolSpecSnapshot
from tradingbot.config.live import PRIMARY_SYMBOL


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


def _ohlc(path: Path, name: str = "XAUUSD_M5_5d.parquet") -> Path:
    bt = path / "data" / "backtest"
    bt.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5, "volume": [1.0] * 5},
        index=idx,
    )
    out = bt / name
    df.to_parquet(out)
    return out


def _catalog_ok() -> ReadOnlyCollectionResult:
    return ReadOnlyCollectionResult(
        ok=True,
        account_environment="DEMO",
        server="LiteFinance-MT5-Demo",
        collection_utc="2026-09-04T12:00:00Z",
        symbol_specs={
            "XAUUSD": {"exists": False, "visible": False, "spec": {}},
            PRIMARY_SYMBOL: {
                "exists": True,
                "visible": True,
                "spec": {"trade_contract_size": 100.0, "point": 0.01, "digits": 2, "swap_long": -1.0},
                "quote": {"bid": 2400.0, "ask": 2400.3},
            },
        },
    )


class TestMt5Attach(unittest.TestCase):
    def test_attach_only_doc(self) -> None:
        self.assertIn("Does NOT start MT5", run_phase25j_mt5_collection.__doc__ or "")

    def test_mt5_unavailable_pass_with_deferral(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25j_mt5_collection(base_dir=tmp)
        self.assertEqual(r.status, "PASS_WITH_DEFERRAL")
        self.assertFalse(r.mt5_connected)
        self.assertFalse(r.mt5_started_by_script)

    def test_bounded_retry_deferred_message(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["No IPC connection"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25j_mt5_collection(base_dir=tmp)
                raw = json.loads((Path(tmp) / "logs/phase25j_bidask_collection_raw.json").read_text())
        self.assertIn("NO IPC", raw.get("operator_note", ""))

    def test_no_symbol_select(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25j_mt5_collection(base_dir=tmp)
        self.assertFalse(r.symbol_select_called)


class TestFreshVsStale(unittest.TestCase):
    def test_deferred_not_fresh(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25j_collection(base_dir=tmp)
        self.assertEqual(r.evidence_class, ReportEvidenceClass.DEFERRED.value)

    def test_fresh_when_connected(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog", return_value=_catalog_ok()):
            with patch("tradingbot.backtest.phase25j_run.collect_historical_ticks") as tm:
                tm.return_value = (_ticks(), {"ok": True, "collection_utc": "2026-09-04T12:00:00Z", "method": "copy_ticks_range"})
                with tempfile.TemporaryDirectory() as tmp:
                    r = run_phase25j_mt5_collection(base_dir=tmp)
        self.assertTrue(r.mt5_connected)
        self.assertEqual(r.evidence_class, FRESH_EVIDENCE_CLASS)


class TestCatalog(unittest.TestCase):
    def test_xauusd_absent(self) -> None:
        cat = _catalog_ok()
        self.assertFalse(cat.symbol_specs["XAUUSD"]["exists"])

    def test_xauusd_i_present(self) -> None:
        cat = _catalog_ok()
        self.assertTrue(cat.symbol_specs[PRIMARY_SYMBOL]["exists"])

    def test_environment_provenance(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog", return_value=_catalog_ok()):
            with patch("tradingbot.backtest.phase25j_run.collect_historical_ticks", return_value=(None, {"ok": False})):
                with tempfile.TemporaryDirectory() as tmp:
                    r = run_phase25j_mt5_collection(base_dir=tmp)
        self.assertEqual(r.account_environment, "DEMO")

    def test_broker_server_provenance(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog", return_value=_catalog_ok()):
            with patch("tradingbot.backtest.phase25j_run.collect_historical_ticks", return_value=(None, {"ok": False})):
                with tempfile.TemporaryDirectory() as tmp:
                    r = run_phase25j_mt5_collection(base_dir=tmp)
        self.assertIn("LiteFinance", r.server)


class TestEquivalence(unittest.TestCase):
    def test_not_proven_xauusd_absent(self) -> None:
        audit = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=False),
            SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, spec={"trade_contract_size": 100.0}),
        )
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_proven_path(self) -> None:
        spec = {"trade_contract_size": 100.0, "point": 0.01, "digits": 2, "tick_size": 0.01, "tick_value": 1.0,
                "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "stops_level": 0, "freeze_level": 0}
        audit = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=True, spec=spec),
            SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, spec=spec),
        )
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.PROVEN.value)

    def test_disproven_path(self) -> None:
        audit = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=True, spec={"trade_contract_size": 50.0}),
            SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, spec={"trade_contract_size": 100.0}),
        )
        self.assertEqual(audit.ev_eq_01, EquivalenceConclusion.DISPROVEN.value)

    def test_no_silent_mapping(self) -> None:
        from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset

        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})


class TestBidAskValidation(unittest.TestCase):
    def test_bid_gt_ask_rejected(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset
        df = pd.DataFrame({"bid": [1.0], "ask": [0.9], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
        r = validate_bidask_dataset(df)
        self.assertFalse(r.ok)

    def test_missing_bid(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset
        df = pd.DataFrame({"ask": [1.0], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_missing_ask(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset
        df = pd.DataFrame({"bid": [1.0], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_tick_provenance_m5(self) -> None:
        bars = ticks_to_m5_bidask_bars(_ticks())
        self.assertIn("bid", bars.columns)
        self.assertIn("ask", bars.columns)

    def test_duplicate_ticks_handled(self) -> None:
        t = _ticks()
        t2 = pd.concat([t, t.head(1)], ignore_index=True)
        bars = ticks_to_m5_bidask_bars(t2)
        self.assertGreater(len(bars), 0)


class TestSpreadIsolation(unittest.TestCase):
    def test_dataset_spread_mode(self) -> None:
        bars = ticks_to_m5_bidask_bars(_ticks())
        model = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=bars)
        self.assertEqual(model.spread_mode, SpreadMode.DATASET)

    def test_proxy_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            matrix = build_dataset_cost_matrix(Path(tmp))
            self.assertTrue(all(r["spread"] == SpreadMode.PROXY.value for r in matrix))


class TestCostClosure(unittest.TestCase):
    def test_commission_unknown(self) -> None:
        deal = parse_closed_deal({"closed_deal": {"commission": 0.0}}, source="t")
        assert deal
        self.assertEqual(audit_commission_evidence([deal]).status, "UNKNOWN")

    def test_zero_commission_not_zero_status(self) -> None:
        deal = parse_closed_deal({"closed_deal": {"commission": 0.0}}, source="t")
        assert deal
        self.assertEqual(summarize_commission([deal]).status, "UNKNOWN")

    def test_slippage_unknown(self) -> None:
        deal = parse_closed_deal({"closed_deal": {"entry_price": 1.0}}, source="t")
        assert deal
        self.assertEqual(deal.slippage_class, SlippageEvidenceClass.UNKNOWN.value)

    def test_requested_vs_fill(self) -> None:
        deal = parse_closed_deal({"closed_deal": {"requested_price": 1.0, "actual_fill_price": 1.01}}, source="t")
        assert deal
        self.assertEqual(deal.slippage_class, SlippageEvidenceClass.REALIZED.value)

    def test_deviation_not_slippage(self) -> None:
        from tradingbot.backtest.cost_evidence_audit import audit_slippage_evidence
        inv = audit_slippage_evidence([])
        self.assertIn("deviation", inv.reasoning.lower())

    def test_swap_broker_rate_only(self) -> None:
        from tradingbot.backtest.cost_evidence_audit import audit_swap_evidence
        inv = audit_swap_evidence([], {"s": {"swap_long": -1.0}})
        self.assertEqual(inv.status, SwapEvidenceClass.BROKER_RATE_ONLY.value)

    def test_historical_swap_unknown(self) -> None:
        from tradingbot.backtest.cost_evidence_audit import audit_swap_evidence
        inv = audit_swap_evidence([], {"s": {"swap_long": -1.0}})
        self.assertIn("historical", inv.reasoning.lower())

    def test_cost_partial_not_complete(self) -> None:
        model = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=ticks_to_m5_bidask_bars(_ticks()))
        self.assertEqual(model.completeness, CostCompleteness.PARTIAL)

    def test_cost_adjusted_metrics_false(self) -> None:
        cfg = BacktestConfig()
        result = BacktestResult(config=cfg, trades=[], equity_curve=[], initial_balance=10000.0, final_balance=10000.0, cost_completeness=CostCompleteness.PARTIAL)
        self.assertFalse(compute_metrics(result)["cost_adjusted_metrics"])


class TestArtifacts(unittest.TestCase):
    def test_closure_audit_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
                mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
                run_phase25j_collection(base_dir=tmp)
            data = json.loads((Path(tmp) / PHASE25J_AUDIT_JSON).read_text())
            self.assertEqual(data["phase"], "25J")
            self.assertFalse(data["credentials_exposed"])

    def test_report_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
                mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
                run_phase25j_collection(base_dir=tmp)
            md = (Path(tmp) / PHASE25J_REPORT_MD).read_text()
            self.assertIn("Phase 25J", md)

    def test_no_credentials(self) -> None:
        audit = run_phase25j_closure_audit()
        self.assertNotIn("password", json.dumps(audit).lower())

    def test_evidence_class_separation(self) -> None:
        md = render_phase25j_report_md(run_phase25j_closure_audit())
        self.assertIn("Stale", md)


class TestImmutability(unittest.TestCase):
    def test_manifest_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            before = build_immutability_manifest(tmp)
            ok, _ = verify_immutability(before, base_dir=tmp)
            self.assertTrue(ok)

    def test_no_synthetic_flag(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog") as mock:
            mock.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
            with tempfile.TemporaryDirectory() as tmp:
                audit = run_phase25j_closure_audit(base_dir=tmp, collection=run_phase25j_mt5_collection(base_dir=tmp))
        self.assertFalse(audit["safety"]["synthetic_data_created"])


class TestFullCollectionMock(unittest.TestCase):
    def test_success_creates_dataset(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog", return_value=_catalog_ok()):
            with patch("tradingbot.backtest.phase25j_run.collect_historical_ticks") as tm:
                tm.return_value = (_ticks(), {"ok": True, "collection_utc": "2026-09-04T12:00:00Z", "method": "copy_ticks_range"})
                with tempfile.TemporaryDirectory() as tmp:
                    r = run_phase25j_collection(base_dir=tmp)
        self.assertTrue(r.bidask_dataset_created)
        self.assertEqual(r.status, "PASS")

    def test_sidecar_no_credentials(self) -> None:
        with patch("tradingbot.backtest.phase25j_run.collect_readonly_symbol_catalog", return_value=_catalog_ok()):
            with patch("tradingbot.backtest.phase25j_run.collect_historical_ticks") as tm:
                tm.return_value = (_ticks(), {"ok": True, "collection_utc": "2026-09-04T12:00:00Z", "method": "copy_ticks_range"})
                with tempfile.TemporaryDirectory() as tmp:
                    run_phase25j_collection(base_dir=tmp)
                    sidecars = list(Path(tmp).rglob("*.metadata.json"))
        self.assertTrue(sidecars, "expected bid/ask sidecar")
        for sc in sidecars:
            if not sc.is_file():
                continue
            data = json.loads(sc.read_text(encoding="utf-8-sig"))
            self.assertTrue(validate_sidecar_no_credentials(data))


class TestDatasetEligibility(unittest.TestCase):
    def test_research_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            matrix = build_dataset_cost_matrix(Path(tmp))
            self.assertTrue(matrix[0]["research_backtest_eligible"])

    def test_closure_preserves_stale(self) -> None:
        audit = run_phase25j_closure_audit()
        self.assertTrue(any("STALE" in s or "2026-09-02" in s for s in audit["stale_evidence"]))


if __name__ == "__main__":
    unittest.main()
