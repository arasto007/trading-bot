"""Phase 8.7 ML backtesting tests (offline only)."""

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

from tradingbot.ml.backtest.broker_sim import BrokerConfig, SimulatedBroker
from tradingbot.ml.backtest.engine import BacktestConfig, BacktestEngine
from tradingbot.ml.backtest.metrics import compute_confusion_matrix, compute_metrics
from tradingbot.ml.backtest.report import load_backtest_run
from tradingbot.ml.backtest.risk import RiskConfig, RiskManager
from tradingbot.ml.backtest.state import BacktestState, EquityPoint, SignalAction, SimulatedTrade, TradeStatus
from tradingbot.ml.backtest.strategy import StrategyConfig, ThresholdStrategy
from tradingbot.ml.data.paths import backtest_equity_path, backtest_metrics_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import create_training_model
from tradingbot.ml.training.model_registry import ModelBundle, next_version, save_model_bundle
from tradingbot.ml.training.trainer import ProductionTrainer

BACKTEST_PKG = ROOT / "tradingbot" / "ml" / "backtest"
PHASE87_FILES = (
    "engine.py",
    "broker_sim.py",
    "strategy.py",
    "risk.py",
    "metrics.py",
    "report.py",
    "state.py",
)
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
    "MetaTrader5",
)
TEST_MIN_SAMPLES = 80


def _scan_files(filenames: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for name in filenames:
        path = BACKTEST_PKG / name
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
                    if module.startswith(prefix) or module == prefix:
                        violations.append(f"{name}: {module}")
    return violations


def _synthetic_source(n: int = 1100, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1], size=n, p=[0.48, 0.52])
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["bos", "choch", "fvg"], size=n),
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
        "volatility_regime": rng.choice([0.0, 0.5, 1.0], size=n),
        "trend_strength": rng.uniform(10, 80, n),
        "h4_trend_bias": rng.choice([-1.0, 0.0, 1.0], size=n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    rows["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.05, n)
    return pd.DataFrame(rows)


def _prepare_model_and_v2(tmp: str) -> str:
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", _synthetic_source())
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    train = ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES)
    result = train.run("XAUUSD", "M5", model="logistic")
    if result.blocked:
        raise RuntimeError(f"training blocked: {result.block_reason}")
    return f"model_v{result.version}.pkl"


class TestStrategy(unittest.TestCase):
    def test_threshold_signals(self):
        s = ThresholdStrategy(StrategyConfig(0.55, 0.45))
        self.assertEqual(s.generate_signal(0.60), SignalAction.BUY)
        self.assertEqual(s.generate_signal(0.40), SignalAction.SELL)
        self.assertEqual(s.generate_signal(0.50), SignalAction.HOLD)


class TestRiskSizing(unittest.TestCase):
    def test_fixed_risk_percent(self):
        rm = RiskManager(RiskConfig(risk_pct=0.005))
        pos = rm.compute_position(10_000.0, risk_unit=10.0)
        self.assertAlmostEqual(pos.risk_amount, 50.0)
        self.assertAlmostEqual(pos.units, 5.0)

    def test_pnl_from_label(self):
        rm = RiskManager()
        pnl_win, r_win = rm.pnl_from_label(1, 100.0, costs=2.0)
        self.assertAlmostEqual(r_win, 2.0)
        self.assertAlmostEqual(pnl_win, 198.0)
        pnl_loss, r_loss = rm.pnl_from_label(0, 100.0, costs=2.0)
        self.assertAlmostEqual(r_loss, -1.0)
        self.assertAlmostEqual(pnl_loss, -102.0)


class TestBrokerSim(unittest.TestCase):
    def test_spread_slippage_on_entry(self):
        broker = SimulatedBroker(BrokerConfig(spread_points=0.4, slippage_points=0.1, commission_per_trade=1.0))
        long_fill = broker.execute_entry(2300.0, 1)
        self.assertGreater(long_fill.fill_price, 2300.0)
        short_fill = broker.execute_entry(2300.0, -1)
        self.assertLess(short_fill.fill_price, 2300.0)


class TestMetrics(unittest.TestCase):
    def test_metrics_on_closed_trades(self):
        state = BacktestState(initial_equity=10_000.0, equity=10_150.0, peak_equity=10_200.0)
        state.closed_trades = [
            SimulatedTrade(
                1, "e1", "2024-01-01T00:00:00+00:00", "XAUUSD", SignalAction.BUY, 1,
                2300, 2290, 2320, 10, 50, 2300.2, 0.6, 1, 1, TradeStatus.CLOSED,
                2320, 100, 2.0, 1.0, 72,
            ),
            SimulatedTrade(
                2, "e2", "2024-01-01T00:05:00+00:00", "XAUUSD", SignalAction.BUY, 1,
                2300, 2290, 2320, 10, 50, 2300.2, 0.6, 1, 0, TradeStatus.CLOSED,
                2290, -50, -1.0, 1.0, 72,
            ),
        ]
        state.equity_curve.append(EquityPoint(timestamp="2024-01-01", equity=10150.0, drawdown=0.01))
        m = compute_metrics(state)
        self.assertEqual(m.num_trades, 2)
        self.assertAlmostEqual(m.win_rate, 0.5)
        self.assertIn("true_positive", compute_confusion_matrix(state.closed_trades))


class TestSequentialIntegrity(unittest.TestCase):
    def test_chronological_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = _prepare_model_and_v2(tmp)
            cfg = BacktestConfig(
                split="test",
                seed=42,
                strategy=StrategyConfig(buy_threshold=0.45, sell_threshold=0.40),
            )
            engine = BacktestEngine(tmp)
            frame = engine.run(model_path, cfg, run_id="run_1")
            self.assertFalse(frame.run_id.startswith("run_run"))

            timestamps = []
            with open(backtest_equity_path("run_1", tmp), encoding="utf-8") as fh:
                for point in json.load(fh):
                    timestamps.append(point["timestamp"])
            self.assertEqual(timestamps, sorted(timestamps))

    def test_no_future_leakage_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            _prepare_model_and_v2(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            test_df = df[df["split"] == "test"].sort_values("timestamp").reset_index(drop=True)
            cols = feature_names()[:5]
            for i in range(1, min(10, len(test_df))):
                self.assertTrue(BacktestEngine.verify_no_future_features(test_df, i, cols))


class TestBacktestEngine(unittest.TestCase):
    def test_end_to_end_backtest(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = _prepare_model_and_v2(tmp)
            cfg = BacktestConfig(
                split="test",
                strategy=StrategyConfig(buy_threshold=0.45, sell_threshold=0.40),
            )
            result = BacktestEngine(tmp).run(model_path, cfg, run_id="run_v1")
            self.assertTrue(backtest_equity_path("run_v1", tmp).is_file())
            self.assertTrue(backtest_metrics_path("run_v1", tmp).is_file())
            report = load_backtest_run("run_v1", tmp)
            self.assertIn("metrics", report)
            self.assertGreaterEqual(result.num_trades, 1)

    def test_empty_trades_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = _prepare_model_and_v2(tmp)
            cfg = BacktestConfig(
                split="test",
                strategy=StrategyConfig(buy_threshold=1.0, sell_threshold=0.0, allow_sell=False),
            )
            result = BacktestEngine(tmp).run(model_path, cfg, run_id="run_empty")
            self.assertEqual(result.num_trades, 0)
            metrics = json.loads(backtest_metrics_path("run_empty", tmp).read_text(encoding="utf-8"))
            self.assertEqual(metrics["num_trades"], 0)

    def test_report_only_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = _prepare_model_and_v2(tmp)
            BacktestEngine(tmp).run(
                model_path,
                BacktestConfig(strategy=StrategyConfig(0.45, 0.40)),
                run_id="run_v1",
            )
            report = BacktestEngine(tmp).report_only("run_v1")
            self.assertEqual(report["run_id"], "run_v1")

    def test_model_version_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DatasetStore(tmp)
            store.store("XAUUSD", "M5", _synthetic_source())
            ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
            splits_data = store.load_v2("XAUUSD", "M5")
            assert splits_data is not None
            from tradingbot.ml.training.data_loader import load_dataset_v2_splits

            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_train, y_train = splits.train_xy()
            X_val, _ = splits.validation_xy()
            X_test, _ = splits.test_xy()
            pipe = FeaturePipeline.from_registry()
            X_s = pipe.fit_transform_train(X_train, X_val, X_test)[0]
            for ver in ("1", "2"):
                model = create_training_model("logistic", seed=42)
                model.fit(X_s, y_train.to_numpy())
                bundle = ModelBundle(version=ver, model=model, feature_pipeline=pipe, metadata={"model_name": "logistic"})
                save_model_bundle(bundle, base_dir=tmp)
            for ver in ("1", "2"):
                result = BacktestEngine(tmp).run(
                    f"model_v{ver}.pkl",
                    BacktestConfig(strategy=StrategyConfig(0.45, 0.40)),
                    run_id=f"run_{ver}",
                )
                self.assertIsNotNone(result.metrics)


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE87_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
