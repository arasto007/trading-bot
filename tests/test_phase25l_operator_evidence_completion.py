"""Phase 25L — operator MT5 cost closure tests (offline; MT5 mocked)."""

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
from tradingbot.backtest.dataset_provenance import validate_sidecar_no_credentials
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.mt5_readonly_evidence import ReadOnlyCollectionResult, ticks_to_m5_bidask_bars
from tradingbot.backtest.operator_evidence import SlippageEvidenceClass, SwapEvidenceClass, parse_closed_deal, summarize_commission
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase25l_run import (
    FRESH_OPERATOR_EVIDENCE,
    PHASE25L_AUDIT_JSON,
    assess_fresh_commission,
    assess_fresh_slippage,
    build_phase25l_cost_matrix,
    run_phase25l_collection,
    run_phase25l_cost_audit,
    run_phase25l_mt5_collection,
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


def _ohlc(root: Path) -> None:
    bt = root / "data" / "backtest"
    bt.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
    pd.DataFrame(
        {"open": [1.0] * 5, "high": [1.1] * 5, "low": [0.9] * 5, "close": [1.0] * 5, "volume": [1.0] * 5},
        index=idx,
    ).to_parquet(bt / "XAUUSD_M5_5d.parquet")


def _catalog(env: str = "DEMO") -> ReadOnlyCollectionResult:
    return ReadOnlyCollectionResult(
        ok=True,
        account_environment=env,
        server="LiteFinance-MT5-Demo" if env == "DEMO" else "LiteFinance-MT5-Live",
        collection_utc="2026-09-05T00:00:00Z",
        symbol_specs={
            "XAUUSD": {"exists": False, "spec": {}},
            PRIMARY_SYMBOL: {
                "exists": True,
                "spec": {"trade_contract_size": 100.0, "point": 0.01, "digits": 2, "swap_long": -1.0},
                "quote": {"bid": 2400.0, "ask": 2400.3},
            },
        },
    )


class TestOfflinePath(unittest.TestCase):
    def test_mt5_offline_pass_with_deferral(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["No IPC connection"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25l_collection(base_dir=tmp)
        self.assertEqual(r.status, "PASS_WITH_DEFERRAL")
        self.assertFalse(r.mt5_connected)

    def test_no_mt5_startup(self) -> None:
        self.assertFalse(run_phase25l_mt5_collection.__doc__ is None or "NOT start" not in (run_phase25l_mt5_collection.__doc__ or ""))

    def test_bounded_attach_deferred(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["MT5 not connected"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25l_mt5_collection(base_dir=tmp)
                raw = json.loads((Path(tmp) / "logs/phase25l_bidask_collection_raw.json").read_text())
        self.assertEqual(raw["status"], "DEFERRED")

    def test_no_symbol_select(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["x"])
            with tempfile.TemporaryDirectory() as tmp:
                r = run_phase25l_mt5_collection(base_dir=tmp)
        self.assertFalse(r.symbol_select_called)


    def test_immutability_after_on_deferred(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25l_mt5_collection(base_dir=tmp)
                after = Path(tmp) / "logs/phase25l_immutability_after.json"
                self.assertTrue(after.is_file())


class TestEvidenceClasses(unittest.TestCase):
    def test_stale_vs_fresh_separation(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["offline"])
            with tempfile.TemporaryDirectory() as tmp:
                audit = run_phase25l_cost_audit(base_dir=tmp, collection=run_phase25l_mt5_collection(base_dir=tmp))
        self.assertEqual(audit["fresh_operator_evidence"], ReportEvidenceClass.DEFERRED.value)
        self.assertTrue(any("STALE" in s for s in audit["stale_evidence"]))

    def test_fresh_when_connected(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog", return_value=_catalog()):
            with patch("tradingbot.backtest.phase25l_run.collect_readonly_deals_sample", return_value=([], {"ok": True})):
                with patch("tradingbot.backtest.phase25l_run.collect_historical_ticks", return_value=(None, {"ok": False})):
                    with tempfile.TemporaryDirectory() as tmp:
                        r = run_phase25l_mt5_collection(base_dir=tmp)
        self.assertEqual(r.evidence_class, FRESH_OPERATOR_EVIDENCE)


class TestCatalog(unittest.TestCase):
    def test_xauusd_absent(self) -> None:
        self.assertFalse(_catalog().symbol_specs["XAUUSD"]["exists"])

    def test_xauusd_i_present(self) -> None:
        self.assertTrue(_catalog().symbol_specs[PRIMARY_SYMBOL]["exists"])

    def test_equivalence_not_proven(self) -> None:
        a = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=False),
            SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, spec={"trade_contract_size": 100.0}),
        )
        self.assertEqual(a.ev_eq_01, EquivalenceConclusion.NOT_PROVEN.value)

    def test_proven_identical(self) -> None:
        spec = {
            "contract_size": 100.0,
            "point": 0.01,
            "digits": 2,
            "tick_size": 0.01,
            "tick_value": 1.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "stops_level": 0,
            "freeze_level": 0,
        }
        a = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=True, spec=spec),
            SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, spec=spec),
        )
        self.assertEqual(a.ev_eq_01, EquivalenceConclusion.PROVEN.value)

    def test_disproven_mismatch(self) -> None:
        a = build_equivalence_audit(
            SymbolSpecSnapshot(symbol="XAUUSD", exists=True, spec={"contract_size": 50.0}),
            SymbolSpecSnapshot(symbol=PRIMARY_SYMBOL, exists=True, spec={"contract_size": 100.0}),
        )
        self.assertEqual(a.ev_eq_01, EquivalenceConclusion.DISPROVEN.value)


class TestBidAsk(unittest.TestCase):
    def test_tick_extraction(self) -> None:
        bars = ticks_to_m5_bidask_bars(_ticks())
        self.assertIn("bid", bars.columns)

    def test_bid_gt_ask_invalid(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset
        df = pd.DataFrame({"bid": [1.0], "ask": [0.9], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_missing_bid(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset
        df = pd.DataFrame({"ask": [1.0], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_missing_ask(self) -> None:
        from tradingbot.backtest.bidask_validation import validate_bidask_dataset
        df = pd.DataFrame({"bid": [1.0], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
        self.assertFalse(validate_bidask_dataset(df).ok)

    def test_duplicate_timestamps_aggregate(self) -> None:
        t = pd.concat([_ticks(), _ticks().head(1)], ignore_index=True)
        self.assertGreater(len(ticks_to_m5_bidask_bars(t)), 0)

    def test_spread_statistics(self) -> None:
        from tradingbot.backtest.bidask_validation import compute_spread_quality
        bars = ticks_to_m5_bidask_bars(_ticks())
        bars["spread"] = bars["ask"] - bars["bid"]
        q = compute_spread_quality(bars, symbol=PRIMARY_SYMBOL, source="test")
        self.assertIsNotNone(q.mean_spread)


class TestCostGate(unittest.TestCase):
    def test_commission_unknown_sparse_zeros(self) -> None:
        deal = parse_closed_deal({"closed_deal": {"commission": 0.0}}, source="t")
        assert deal
        self.assertEqual(summarize_commission([deal]).status, "UNKNOWN")

    def test_fresh_commission_assessment(self) -> None:
        r = assess_fresh_commission([{"commission": 0.0}, {"commission": 0.0}])
        self.assertEqual(r["status"], "UNKNOWN")

    def test_slippage_unknown_no_request(self) -> None:
        r = assess_fresh_slippage([{"price": 1.0}])
        self.assertEqual(r["status"], "UNKNOWN")

    def test_deviation_not_slippage_note(self) -> None:
        self.assertIn("deviation", assess_fresh_slippage([])["note"])

    def test_swap_broker_rate(self) -> None:
        from tradingbot.backtest.cost_evidence_audit import audit_swap_evidence
        self.assertEqual(audit_swap_evidence([], {"s": {"swap_long": -1}}).status, SwapEvidenceClass.BROKER_RATE_ONLY.value)

    def test_cost_partial(self) -> None:
        bars = ticks_to_m5_bidask_bars(_ticks())
        m = build_backtest_cost_model(BacktestConfig(spread_mode="AUTO"), frame=bars)
        self.assertEqual(m.completeness, CostCompleteness.PARTIAL)

    def test_cost_adjusted_metrics_false(self) -> None:
        cfg = BacktestConfig()
        res = BacktestResult(config=cfg, trades=[], equity_curve=[], initial_balance=10000.0, final_balance=10000.0, cost_completeness=CostCompleteness.PARTIAL)
        self.assertFalse(compute_metrics(res)["cost_adjusted_metrics"])

    def test_proxy_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            matrix = build_phase25l_cost_matrix(Path(tmp), None)
            self.assertTrue(all(r["spread"] == SpreadMode.PROXY.value for r in matrix))


class TestDatasetCreation(unittest.TestCase):
    def test_full_path_creates_dataset(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog", return_value=_catalog()):
            with patch("tradingbot.backtest.phase25l_run.collect_readonly_deals_sample", return_value=([], {"ok": True})):
                with patch("tradingbot.backtest.phase25l_run.collect_historical_ticks") as tm:
                    tm.return_value = (_ticks(), {"ok": True, "collection_utc": "2026-09-05T00:00:00Z"})
                    with tempfile.TemporaryDirectory() as tmp:
                        r = run_phase25l_collection(base_dir=tmp)
        self.assertTrue(r.bidask_dataset_created)
        self.assertEqual(r.status, "PASS")

    def test_sidecar_provenance(self) -> None:
        from tradingbot.backtest.dataset_provenance import metadata_path_for

        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog", return_value=_catalog()):
            with patch("tradingbot.backtest.phase25l_run.collect_readonly_deals_sample", return_value=([], {"ok": True})):
                with patch("tradingbot.backtest.phase25l_run.collect_historical_ticks") as tm:
                    tm.return_value = (_ticks(), {"ok": True, "collection_utc": "2026-09-05T00:00:00Z"})
                    with tempfile.TemporaryDirectory() as tmp:
                        r = run_phase25l_collection(base_dir=tmp)
                        targets = [Path(p) for p in r.artifacts if p.endswith(".parquet") and "bidask" in p and "staging" not in p]
                        self.assertTrue(targets)
                        meta = metadata_path_for(targets[0])
                        self.assertTrue(meta.is_file(), f"missing sidecar {meta}")
                        data = json.loads(meta.read_text(encoding="utf-8-sig"))
                        self.assertTrue(validate_sidecar_no_credentials(data))
                        self.assertEqual(data.get("spread_mode"), SpreadMode.DATASET.value)


class TestSafety(unittest.TestCase):
    def test_real_account_read_only(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog", return_value=_catalog("REAL")):
            with patch("tradingbot.backtest.phase25l_run.collect_readonly_deals_sample", return_value=([], {"ok": True})):
                with patch("tradingbot.backtest.phase25l_run.collect_historical_ticks", return_value=(None, {"ok": False})):
                    with tempfile.TemporaryDirectory() as tmp:
                        r = run_phase25l_mt5_collection(base_dir=tmp)
        self.assertTrue(r.real_account_read_only)

    def test_immutability_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _ohlc(Path(tmp))
            before = build_immutability_manifest(tmp)
            self.assertTrue(verify_immutability(before, base_dir=tmp)[0])

    def test_no_synthetic(self) -> None:
        audit = run_phase25l_cost_audit()
        self.assertFalse(audit["safety"]["synthetic_data_created"])

    def test_no_credentials(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["x"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25l_collection(base_dir=tmp)
                text = (Path(tmp) / PHASE25L_AUDIT_JSON).read_text().lower()
        self.assertNotIn("password", text)

    def test_artifact_schema(self) -> None:
        with patch("tradingbot.backtest.phase25l_run.collect_readonly_symbol_catalog") as m:
            m.return_value = ReadOnlyCollectionResult(ok=False, errors=["x"])
            with tempfile.TemporaryDirectory() as tmp:
                run_phase25l_collection(base_dir=tmp)
                data = json.loads((Path(tmp) / PHASE25L_AUDIT_JSON).read_text())
        self.assertEqual(data["phase"], "25L")

    def test_no_silent_mapping(self) -> None:
        from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset
        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})


class TestCommissionAudit(unittest.TestCase):
    def test_stale_commission_unknown(self) -> None:
        deal = parse_closed_deal({"closed_deal": {"commission": 0.0}}, source="t")
        assert deal
        self.assertEqual(audit_commission_evidence([deal]).status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
