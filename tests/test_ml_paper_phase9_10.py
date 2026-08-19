"""Phase 9.10 paper trading & shadow validation tests (offline only)."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import (
    paper_trading_config_path,
    paper_trading_equity_path,
    paper_trading_metrics_path,
    paper_trading_report_path,
    paper_trading_signals_path,
    paper_trading_state_path,
    paper_trading_trades_path,
    phase9_9_artifacts_root,
    phase9_9_config_path,
    phase9_9_feature_order_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.paper_trading.market_stream import MarketStream
from tradingbot.ml.paper_trading.model_registry import (
    build_test_freeze_contract,
    freeze_phase9_9_artifacts,
    load_phase9_9_bundle,
    verify_bundle_integrity,
)
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker
from tradingbot.ml.paper_trading.performance_tracker import PerformanceTracker
from tradingbot.ml.paper_trading.position_manager import PositionManager
from tradingbot.ml.paper_trading.report import load_report, save_run
from tradingbot.ml.paper_trading.shadow_engine import ShadowEngine
from tradingbot.ml.paper_trading.signal_engine import PaperSignal, SignalConfig, SignalEngine
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

PAPER_PKG = ROOT / "tradingbot" / "ml" / "paper_trading"
PAPER_FILES = (
    "__init__.py",
    "model_registry.py",
    "signal_engine.py",
    "paper_broker.py",
    "position_manager.py",
    "performance_tracker.py",
    "market_stream.py",
    "shadow_engine.py",
    "report.py",
)
FORBIDDEN = (
    "TradingKernel",
    "RiskGate",
    "mt5_execution",
    "order_send",
    "tradingbot.execution",
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
)
PHASE99_FEATURES = ("ema50_slope", "candle_direction", "structure_distance")
TEST_MIN_SAMPLES = 80


def _scan_forbidden() -> list[str]:
    violations: list[str] = []
    for name in PAPER_FILES:
        path = PAPER_PKG / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for module in mods:
                for prefix in FORBIDDEN:
                    if prefix in module or module == prefix:
                        violations.append(f"{name}: {module}")
    return violations


def _synthetic_source(n: int = 1200, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["order_block", "choch", "fvg", "bos"], size=n),
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "timeframe_role": "entry_execution",
        "entry_price": 2300.0 + rng.normal(0, 1, n),
        "direction": rng.choice([1, -1], size=n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": labels,
        "future_window_bars": 72,
        "tp_hit": labels == 1,
        "sl_hit": labels == 0,
        "mfe": rng.uniform(0, 2, n),
        "mae": rng.uniform(0, 1, n),
        "future_return": rng.normal(0, 0.01, n),
        "risk_unit": rng.uniform(2, 8, n),
        "split": "train",
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": 0.5,
        "trend_strength": 15.0,
        "h4_trend_bias": 0.0,
        "atr_percentile": 45.0,
        "ema_cross_state": 0.0,
        "ema50_slope": 0.0,
        "atr_14": rng.uniform(3, 8, n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    df = pd.DataFrame(rows)
    n_train = int(n * 0.7)
    n_val = int(n * 0.15)
    splits = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    df["split"] = splits
    return df


def _setup_paper(tmp: str) -> str:
    store = DatasetStore(tmp)
    raw = _synthetic_source()
    store.store("XAUUSD", "M5", raw)
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    v2 = store.load_v2("XAUUSD", "M5")
    assert v2 is not None
    contract = build_test_freeze_contract()
    freeze_phase9_9_artifacts(v2, contract=contract, base_dir=tmp, seed=42)
    return dataset_content_fingerprint(v2)


class TestPhase910PaperTrading(unittest.TestCase):
    def test_forbidden_imports_zero(self):
        self.assertEqual(_scan_forbidden(), [])

    def test_model_loading_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            bundle = freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp, seed=42)
            self.assertTrue(phase9_9_model_path(tmp).is_file())
            self.assertTrue(phase9_9_scaler_path(tmp).is_file())
            loaded = load_phase9_9_bundle(base_dir=tmp, build_if_missing=False)
            self.assertEqual(loaded.feature_order, list(PHASE99_FEATURES))

    def test_feature_order_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp)
            order = json.loads(phase9_9_feature_order_path(tmp).read_text())["feature_order"]
            cfg = json.loads(phase9_9_config_path(tmp).read_text())
            self.assertEqual(order, cfg["features"])

    def test_frozen_config_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp)
            cfg = json.loads(phase9_9_config_path(tmp).read_text())
            self.assertEqual(cfg["model"], "LogisticRegression")
            self.assertAlmostEqual(cfg["parameters"]["C"], 0.1)
            self.assertEqual(cfg["regime"], "RANGE")
            self.assertAlmostEqual(cfg["risk_pct"], 0.005)

    def test_bundle_integrity_predict(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            bundle = freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp)
            feats = {f: float(df.iloc[0][f]) for f in bundle.feature_order}
            result = verify_bundle_integrity(bundle, feats)
            self.assertTrue(result.passed)

    def test_signal_buy_threshold(self):
        eng = SignalEngine(SignalConfig(0.55, 0.45))
        self.assertEqual(eng.generate(0.55), PaperSignal.BUY)
        self.assertEqual(eng.generate(0.60), PaperSignal.BUY)

    def test_signal_sell_threshold(self):
        eng = SignalEngine(SignalConfig(0.55, 0.45))
        self.assertEqual(eng.generate(0.45), PaperSignal.SELL)
        self.assertEqual(eng.generate(0.40), PaperSignal.SELL)

    def test_signal_hold(self):
        eng = SignalEngine(SignalConfig(0.55, 0.45))
        self.assertEqual(eng.generate(0.50), PaperSignal.HOLD)

    def test_broker_sl_tp(self):
        broker = PaperBroker(BrokerConfig(tp_r=2.0, sl_r=1.0))
        sl, tp = broker.sl_tp(2300.0, 1, 10.0)
        self.assertAlmostEqual(sl, 2290.0)
        self.assertAlmostEqual(tp, 2320.0)

    def test_broker_resolve_bar_tp(self):
        broker = PaperBroker()
        bar = pd.Series({"high": 2325.0, "low": 2295.0})
        hit = broker.resolve_bar(bar, direction=1, stop_loss=2290.0, take_profit=2320.0)
        self.assertEqual(hit, ("TP", 2320.0))

    def test_broker_resolve_bar_sl(self):
        broker = PaperBroker()
        bar = pd.Series({"high": 2305.0, "low": 2285.0})
        hit = broker.resolve_bar(bar, direction=1, stop_loss=2290.0, take_profit=2320.0)
        self.assertEqual(hit, ("SL", 2290.0))

    def test_risk_calculation(self):
        tracker = PerformanceTracker(initial_equity=10_000.0, equity=10_000.0, peak_equity=10_000.0)
        risk_amount = tracker.equity * 0.005
        self.assertAlmostEqual(risk_amount, 50.0)

    def test_position_max_one(self):
        mgr = PositionManager(max_open=1)
        self.assertTrue(mgr.can_open())
        mgr.open(
            timestamp="t1",
            symbol="XAUUSD",
            direction=1,
            entry=2300,
            fill_price=2300.1,
            stop_loss=2290,
            take_profit=2320,
            risk_unit=10,
            risk_amount=50,
            probability=0.6,
            signal="BUY",
        )
        self.assertFalse(mgr.can_open())

    def test_duplicate_signal_blocked(self):
        mgr = PositionManager(max_open=1)
        kwargs = dict(
            symbol="XAUUSD",
            direction=1,
            entry=2300,
            fill_price=2300.1,
            stop_loss=2290,
            take_profit=2320,
            risk_unit=10,
            risk_amount=50,
            probability=0.6,
            signal="BUY",
        )
        mgr.open(timestamp="t1", **kwargs)
        mgr.close("TP", 2320, 2.0, 100)
        self.assertFalse(mgr.can_signal("t1"))

    def test_empty_trade_metrics(self):
        mgr = PositionManager()
        tracker = PerformanceTracker()
        metrics = tracker.compute(mgr)
        self.assertEqual(metrics.num_trades, 0)
        self.assertEqual(metrics.win_rate, 0.0)

    def test_sequential_candle_iteration(self):
        ts = pd.date_range("2024-01-01", periods=100, freq="5min", tz="UTC")
        candles = pd.DataFrame(
            {
                "open": 2300.0,
                "high": 2305.0,
                "low": 2295.0,
                "close": 2300.0,
                "volume": 100,
            },
            index=ts,
        )
        indices = [i for i, _ in MarketStream().iter_closed_bars(candles, start_index=60)]
        self.assertEqual(indices, list(range(60, 100)))

    def test_no_dataset_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup_paper(tmp)
            ShadowEngine(base_dir=tmp).run("XAUUSD", "M5", run_id="run_test", shadow_days=365)
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_shadow_run_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            result = ShadowEngine(base_dir=tmp).run("XAUUSD", "M5", run_id="run_v1", shadow_days=365)
            self.assertTrue(paper_trading_trades_path("run_v1", tmp).is_file())
            self.assertTrue(paper_trading_equity_path("run_v1", tmp).is_file())
            self.assertTrue(paper_trading_metrics_path("run_v1", tmp).is_file())
            self.assertTrue(paper_trading_signals_path("run_v1", tmp).is_file())
            self.assertTrue(paper_trading_report_path("run_v1", tmp).is_file())
            report = load_report("run_v1", tmp)
            self.assertEqual(report["phase"], "9.10")
            self.assertFalse(report.get("order_send", True))

    def test_restart_state_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            ShadowEngine(base_dir=tmp).run("XAUUSD", "M5", run_id="run_resume", shadow_days=365)
            state = json.loads(paper_trading_state_path("run_resume", tmp).read_text())
            self.assertIn("trade_counter", state)
            self.assertIn("equity", state)

    def test_report_only_cli_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            engine = ShadowEngine(base_dir=tmp)
            engine.run("XAUUSD", "M5", run_id="run_report", shadow_days=365)
            report = engine.report_only("run_report")
            self.assertIn("metrics", report)

    def test_sequential_signal_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            ShadowEngine(base_dir=tmp).run("XAUUSD", "M5", run_id="run_seq", shadow_days=365)
            signals = json.loads(paper_trading_signals_path("run_seq", tmp).read_text())
            ts_list = [s["timestamp"] for s in signals]
            self.assertEqual(ts_list, sorted(ts_list))

    def test_full_shadow_run_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            result = ShadowEngine(base_dir=tmp).run("XAUUSD", "M5", run_id="run_full", shadow_days=365)
            self.assertGreaterEqual(result.num_trades, 1)
            self.assertEqual(result.status, "PASS")

    def test_metadata_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_paper(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            contract = build_test_freeze_contract()
            freeze_phase9_9_artifacts(df, contract=contract, base_dir=tmp)
            meta = json.loads(phase9_9_metadata_path(tmp).read_text())
            self.assertEqual(meta["phase"], "9.9")
            self.assertEqual(meta["feature_subset"], "stable_top3")


if __name__ == "__main__":
    unittest.main()
