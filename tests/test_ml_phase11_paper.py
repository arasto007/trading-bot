"""Phase 11 kernel paper trading tests (offline)."""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import paper_trading_final_report_path, paper_trading_trades_path
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast
from tradingbot.ml.paper.config import PaperTradingConfig, validate_frozen_model
from tradingbot.ml.paper.paper_engine import KernelPaperEngine
from tradingbot.ml.paper.paper_execution import PaperExecutionEngine, VirtualOrder
from tradingbot.ml.paper.performance import compute_performance
from tradingbot.ml.paper.trade_lifecycle import TradeLifecycle
from tradingbot.ml.paper_trading.model_registry import build_test_freeze_contract, freeze_phase9_9_artifacts

PAPER_PKG = ROOT / "tradingbot" / "ml" / "paper"


def _candles(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-06-01", periods=n, freq="5min", tz="UTC")
    closes = 2300.0 + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 0.5,
            "low": closes - 0.5,
            "close": closes,
            "volume": rng.integers(50, 200, n),
        },
        index=idx,
    )


def _dataset(n: int = 1200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["order_block", "choch", "fvg", "bos"], size=n),
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "entry_price": 2300.0 + rng.normal(0, 1, n),
        "direction": rng.choice([1, -1], size=n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": rng.choice([0, 1], size=n),
        "risk_unit": rng.uniform(2, 8, n),
        "split": "train",
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": 0.5,
        "trend_strength": 15.0,
        "h4_trend_bias": 0.0,
        "atr_percentile": 45.0,
        "ema_cross_state": 0.0,
        "ema50_slope": 0.0,
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    return pd.DataFrame(rows)


def _setup(tmp: str) -> pd.DataFrame:
    candles = _candles()
    CandleStore(tmp).store("XAUUSD", "M5", candles)
    store = DatasetStore(tmp)
    raw = _dataset()
    store.store_v2("XAUUSD", "M5", raw)
    freeze_phase9_9_artifacts(raw, contract=build_test_freeze_contract(), base_dir=tmp, seed=42)
    return candles


class TestPhase11Paper(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["ENABLE_ML_SHADOW"] = "true"
        os.environ["ML_SHADOW_MODE"] = "true"

    def test_ast_safety_scan(self):
        self.assertEqual(scan_live_shadow_ast(), [])

    def test_no_execution_imports_in_paper_modules(self):
        forbidden = {"order_send", "positions_get", "Mt5ExecutionAdapter", "mt5_execution"}
        for name in (
            "paper_engine.py",
            "paper_execution.py",
            "virtual_account.py",
            "portfolio_manager.py",
            "trade_lifecycle.py",
        ):
            tree = ast.parse((PAPER_PKG / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for token in forbidden:
                            self.assertNotIn(token, alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for token in forbidden:
                        self.assertNotIn(token, node.module)

    def test_model_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = validate_frozen_model(base_dir=tmp)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(len(report["feature_order"]), 3)

    def test_paper_execution_integrity(self):
        candles = _candles()
        engine = PaperExecutionEngine(risk_percent=0.005)
        order, invalid = engine.create_order(
            candles=candles,
            bar_index=120,
            direction="BUY",
            symbol="XAUUSD",
            timestamp="t",
            equity=10_000.0,
        )
        self.assertIsNotNone(order)
        self.assertIsNone(invalid)
        self.assertAlmostEqual(order.rr_ratio, 2.0, places=1)
        self.assertNotEqual(order.entry, order.sl)

    def test_trade_lifecycle_sl_tp(self):
        lifecycle = TradeLifecycle()
        order = VirtualOrder(
            symbol="XAUUSD",
            direction="BUY",
            entry=100.0,
            sl=99.0,
            tp=102.0,
            risk_percent=0.005,
            position_size=1.0,
            lot=0.01,
            timestamp="t",
        )
        trade = lifecycle.open_trade(order, risk_amount=50.0)
        bar = pd.Series({"open": 100, "high": 102.5, "low": 99.5, "close": 101})
        closed = lifecycle.monitor(trade, bar)
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertEqual(closed.result, "TP")

    def test_performance_metrics(self):
        lifecycle = TradeLifecycle()
        order = VirtualOrder(
            symbol="XAUUSD",
            direction="BUY",
            entry=100.0,
            sl=99.0,
            tp=102.0,
            risk_percent=0.005,
            position_size=1.0,
            lot=0.01,
            timestamp="t",
        )
        t = lifecycle.open_trade(order, risk_amount=50.0)
        t = lifecycle._close(t, "TP", 102.0)
        metrics = compute_performance([t], virtual_executions=1)
        self.assertEqual(metrics["trading"]["total_trades"], 1)
        self.assertFalse(metrics["execution"]["order_send"])

    def test_kernel_paper_engine_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = PaperTradingConfig(
                paper_days=7,
                skip_preflight=True,
                candles_df=candles,
            )
            result = KernelPaperEngine(base_dir=tmp).run(cfg, run_id="run_phase11_test")
            self.assertTrue(paper_trading_final_report_path("run_phase11_test", tmp).is_file())
            self.assertEqual(result.metrics["execution"]["order_send"], False)
            self.assertEqual(result.metrics["execution"]["integrity_failures"], 0)

    def test_reports_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _setup(tmp)
            cfg = PaperTradingConfig(paper_days=7, skip_preflight=True, candles_df=candles)
            KernelPaperEngine(base_dir=tmp).run(cfg, run_id="run_phase11_reports")
            self.assertTrue(paper_trading_trades_path("run_phase11_reports", tmp).is_file())

    def test_deterministic_execution_engine(self):
        candles = _candles()
        a = PaperExecutionEngine().create_order(
            candles=candles, bar_index=120, direction="SELL", symbol="XAUUSD", timestamp="t", equity=10_000
        )[0]
        b = PaperExecutionEngine().create_order(
            candles=candles, bar_index=120, direction="SELL", symbol="XAUUSD", timestamp="t", equity=10_000
        )[0]
        assert a is not None and b is not None
        self.assertEqual(a.entry, b.entry)
        self.assertEqual(a.sl, b.sl)


if __name__ == "__main__":
    unittest.main()
