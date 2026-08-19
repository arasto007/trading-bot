"""Phase 9.7 production backtesting tests (offline only)."""

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

from tradingbot.ml.backtest.broker_simulator import BrokerConfig, SimulatedBroker
from tradingbot.ml.backtest.metrics import compute_metrics
from tradingbot.ml.backtest.model_loader import build_phase9_6_artifacts, load_phase9_6_bundle, verify_integrity
from tradingbot.ml.backtest.phase97_engine import Phase97BacktestEngine
from tradingbot.ml.backtest.risk import RiskConfig, RiskManager
from tradingbot.ml.backtest.strategy import StrategyConfig, ThresholdStrategy
from tradingbot.ml.backtest.trade_state import PositionState, TradeStateMachine
from tradingbot.ml.backtest.engine import BacktestConfig, BacktestEngine
from tradingbot.ml.backtest.state import BacktestState, EquityPoint, SignalAction, SimulatedTrade, TradeStatus
from tradingbot.ml.data.paths import (
    backtest_equity_path,
    backtest_metrics_path,
    backtest_report_path,
    phase9_6_optimization_report_path,
    production_best_model_path,
    regime_optimization_dataset_path,
)
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

BACKTEST_PKG = ROOT / "tradingbot" / "ml" / "backtest"
PHASE97_FILES = (
    "engine.py",
    "broker_sim.py",
    "broker_simulator.py",
    "strategy.py",
    "risk.py",
    "metrics.py",
    "report.py",
    "state.py",
    "trade_state.py",
    "model_loader.py",
    "phase97_engine.py",
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
STABLE_FEATURES = ("ema50_slope", "candle_direction", "structure_distance", "ema_cross_state")


def _scan_files(filenames: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for name in filenames:
        path = BACKTEST_PKG / name
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
                    if module.startswith(prefix) or module == prefix:
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
    rows["h4_trend_bias"] = np.where(labels == 1, 0.5, -0.5)
    df = pd.DataFrame(rows)
    n_train = int(n * 0.7)
    n_val = int(n * 0.15)
    splits = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    df["split"] = splits
    return df


def _write_phase96_report(tmp: str, fingerprint: str) -> None:
    config_id = "RANGE__A_all_events__A_top10_stable"
    report = {
        "phase": "9.6",
        "dataset": {"fingerprint": fingerprint, "rows": 1200},
        "best_configuration": {
            "regime": "RANGE",
            "event_filter": "A_all_events",
            "feature_set": "A_top10_stable",
            "model": "logistic",
        },
        "feature_findings": {
            "feature_sets": {"A_top10_stable": list(STABLE_FEATURES)},
            "stable_features": list(STABLE_FEATURES),
        },
        "model_optimization": {
            "best_candidate": {
                "variant_id": config_id,
                "hyperparameters": {},
                "model_name": "logistic",
            }
        },
    }
    path = phase9_6_optimization_report_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _setup_phase97(tmp: str) -> str:
    store = DatasetStore(tmp)
    raw = _synthetic_source()
    store.store("XAUUSD", "M5", raw)
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    v2 = store.load_v2("XAUUSD", "M5")
    assert v2 is not None
    fp = dataset_content_fingerprint(v2)
    _write_phase96_report(tmp, fp)
    resolved = v2[v2["label"].isin([0, 1])].copy()
    resolved["market_regime"] = assign_market_regime(resolved)
    range_df = resolved[resolved["market_regime"] == "RANGE"].copy()
    if len(range_df) < 120:
        range_df = resolved.copy()
        range_df["trend_strength"] = 15.0
        range_df["atr_percentile"] = 45.0
        range_df["volatility_regime"] = 0.5
    path = regime_optimization_dataset_path("XAUUSD", "M5", "RANGE__A_all_events__A_top10_stable", tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    range_df.to_parquet(path, index=False)
    build_phase9_6_artifacts("XAUUSD", "M5", base_dir=tmp, seed=42)
    return fp


class TestPhase97Backtest(unittest.TestCase):
    def test_chronological_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            cfg = BacktestConfig(split="test", strategy=StrategyConfig(0.45, 0.40))
            result = Phase97BacktestEngine(tmp).run(cfg, run_id="phase9_7_test", seed=42)
            ts = [p["timestamp"] for p in json.loads(backtest_equity_path("phase9_7_test", tmp).read_text())]
            self.assertEqual(ts, sorted(ts))
            self.assertGreaterEqual(result.num_trades, 1)

    def test_no_future_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            test_df = df[df["split"] == "test"].sort_values("timestamp").reset_index(drop=True)
            cols = list(STABLE_FEATURES)
            for i in range(1, min(10, len(test_df))):
                self.assertTrue(BacktestEngine.verify_no_future_features(test_df, i, cols))

    def test_dataset_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup_phase97(tmp)
            Phase97BacktestEngine(tmp).run(BacktestConfig(split="test", strategy=StrategyConfig(0.45, 0.40)), seed=42)
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_model_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            bundle = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            self.assertEqual(len(bundle.feature_order), 4)
            self.assertEqual(bundle.configuration["regime"], "RANGE")

    def test_scaler_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            bundle = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            integrity = verify_integrity(bundle, df)
            self.assertTrue(integrity.passed)

    def test_signal_generation(self):
        s = ThresholdStrategy(StrategyConfig(0.55, 0.45))
        self.assertEqual(s.generate_signal(0.60), SignalAction.BUY)
        self.assertEqual(s.generate_signal(0.50), SignalAction.HOLD)

    def test_buy_threshold(self):
        s = ThresholdStrategy(StrategyConfig(0.55, 0.45))
        self.assertTrue(s.should_trade(s.generate_signal(0.56)))

    def test_sell_threshold(self):
        s = ThresholdStrategy(StrategyConfig(0.55, 0.45))
        self.assertTrue(s.should_trade(s.generate_signal(0.40)))

    def test_risk_sizing_correctness(self):
        rm = RiskManager(RiskConfig(risk_pct=0.005))
        pos = rm.compute_position(10_000.0, 10.0, atr=12.0)
        self.assertAlmostEqual(pos.risk_amount, 50.0)
        self.assertAlmostEqual(pos.units, 50.0 / 12.0)

    def test_sl_tp_calculation(self):
        rm = RiskManager(RiskConfig(tp_r_multiple=2.0, sl_r_multiple=1.0))
        pnl_win, r_win = rm.pnl_from_label(1, 100.0, costs=0.0)
        pnl_loss, r_loss = rm.pnl_from_label(0, 100.0, costs=0.0)
        self.assertAlmostEqual(r_win, 2.0)
        self.assertAlmostEqual(r_loss, -1.0)
        self.assertAlmostEqual(pnl_win, 200.0)
        self.assertAlmostEqual(pnl_loss, -100.0)

    def test_position_state_machine(self):
        sm = TradeStateMachine()
        self.assertEqual(sm.position, PositionState.FLAT)
        trade = SimulatedTrade(
            1, "e1", "t", "XAUUSD", SignalAction.BUY, 1,
            2300, 2290, 2320, 10, 50, 2300, 0.6, 1, 1,
        )
        sm.enter(trade)
        self.assertEqual(sm.position, PositionState.LONG)
        sm.close(trade)
        self.assertEqual(sm.position, PositionState.FLAT)

    def test_spread_simulation(self):
        broker = SimulatedBroker(BrokerConfig(spread_points=0.4, slippage_points=0.0))
        fill = broker.execute_entry(2300.0, 1)
        self.assertGreater(fill.fill_price, 2300.0)

    def test_slippage_simulation(self):
        broker = SimulatedBroker(BrokerConfig(spread_points=0.0, slippage_points=0.2))
        fill = broker.execute_entry(2300.0, -1)
        self.assertLess(fill.fill_price, 2300.0)

    def test_commission_calculation(self):
        broker = SimulatedBroker(BrokerConfig(commission_per_trade=2.5))
        fill = broker.execute_entry(2300.0, 1)
        self.assertGreaterEqual(fill.costs, 2.5)

    def test_pnl_calculation(self):
        rm = RiskManager()
        pnl, r = rm.pnl_from_label(1, 50.0, costs=1.0)
        self.assertAlmostEqual(pnl, 99.0)

    def test_drawdown_calculation(self):
        state = BacktestState(initial_equity=10_000.0, equity=9_500.0, peak_equity=10_000.0)
        state.record_equity("2024-01-01")
        self.assertGreater(state.equity_curve[0].drawdown, 0.0)
        state.closed_trades = [
            SimulatedTrade(
                1, "e1", "2024-01-01", "XAUUSD", SignalAction.BUY, 1,
                2300, 2290, 2320, 10, 50, 2300, 0.6, 1, 0, TradeStatus.CLOSED,
                2290, -50, -1.0, 1.0, 72,
            ),
        ]
        m = compute_metrics(state)
        self.assertGreater(m.max_drawdown, 0.0)

    def test_equity_curve_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            Phase97BacktestEngine(tmp).run(
                BacktestConfig(split="test", strategy=StrategyConfig(0.45, 0.40)),
                run_id="eq_test",
                seed=42,
            )
            self.assertTrue(backtest_equity_path("eq_test", tmp).is_file())

    def test_empty_trade_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            result = Phase97BacktestEngine(tmp).run(
                BacktestConfig(split="test", strategy=StrategyConfig(1.0, 0.0, allow_sell=False)),
                run_id="empty_test",
                seed=42,
            )
            self.assertEqual(result.num_trades, 0)
            metrics = json.loads(backtest_metrics_path("empty_test", tmp).read_text())
            self.assertEqual(metrics["num_trades"], 0)

    def test_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            cfg = BacktestConfig(split="test", strategy=StrategyConfig(0.45, 0.40), seed=42)
            r1 = Phase97BacktestEngine(tmp).run(cfg, run_id="det1", seed=42)
            r2 = Phase97BacktestEngine(tmp).run(cfg, run_id="det2", seed=42)
            self.assertEqual(r1.num_trades, r2.num_trades)
            self.assertEqual(r1.metrics.win_rate, r2.metrics.win_rate)

    def test_forbidden_imports_ast_scan(self):
        self.assertEqual(_scan_files(PHASE97_FILES), [])

    def test_no_production_model_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            prod = production_best_model_path(tmp)
            mtime = prod.stat().st_mtime if prod.is_file() else None
            Phase97BacktestEngine(tmp).run(BacktestConfig(split="test", strategy=StrategyConfig(0.45, 0.40)), seed=42)
            if mtime is not None:
                self.assertEqual(prod.stat().st_mtime, mtime)

    def test_end_to_end_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_phase97(tmp)
            result = Phase97BacktestEngine(tmp).run(
                BacktestConfig(split="test", strategy=StrategyConfig(0.45, 0.40)),
                run_id="phase9_7_v1",
                seed=42,
            )
            self.assertEqual(result.leakage_audit, "PASS")
            self.assertTrue(backtest_report_path("phase9_7_v1", tmp).is_file())


if __name__ == "__main__":
    unittest.main()
