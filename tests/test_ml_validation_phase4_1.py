"""Phase 4.1 model validation framework tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry import feature_names
from tradingbot.ml.models.training import train_baseline_model
from tradingbot.ml.validation.calibration import run_calibration
from tradingbot.ml.validation.cross_validation import run_cross_validation
from tradingbot.ml.validation.feature_ablation import run_feature_ablation
from tradingbot.ml.validation.regime_test import run_regime_analysis
from tradingbot.ml.validation.report import run_full_validation
from tradingbot.ml.validation.robustness import run_robustness_tests
from tradingbot.ml.validation.threshold_optimizer import optimize_threshold
from tradingbot.ml.validation.trading_simulator import TP_R, SL_R, simulate_trades
from tradingbot.ml.validation.walk_forward import run_walk_forward
from tradingbot.ml.validation._utils import load_resolved_dataset


def _make_dataset(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    n_train = int(n * 0.70)
    n_val = int(n * 0.15)
    splits = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])

    row: dict = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": "bos",
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "timeframe_role": "entry_execution",
        "entry_price": 2300.0,
        "direction": rng.choice([1, -1], n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": labels,
        "future_window_bars": 72,
        "tp_hit": labels == 1,
        "sl_hit": labels == 0,
        "mfe": rng.uniform(0, 2, n),
        "mae": rng.uniform(0, 1, n),
        "future_return": rng.normal(0, 0.01, n),
        "risk_unit": 10.0,
        "split": splits,
        "dataset_schema_version": "1.0",
    }
    for feat in feature_names():
        row[feat] = rng.normal(0, 1, n)

    row["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.1, n)
    row["trend_strength"] = rng.uniform(10, 40, n)
    row["volatility_regime"] = rng.choice([0.0, 0.5, 1.0], n)
    row["atr_percentile"] = rng.uniform(10, 90, n)
    row["session_london"] = rng.choice([0.0, 1.0], n, p=[0.7, 0.3])
    row["session_ny"] = rng.choice([0.0, 1.0], n, p=[0.7, 0.3])
    row["session_asia"] = rng.choice([0.0, 1.0], n, p=[0.7, 0.3])
    return pd.DataFrame(row)


def _setup(tmp: str) -> None:
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", _make_dataset())
    store.save_build_manifest(
        "XAUUSD",
        "M5",
        {"dataset_hash": "valhash", "feature_version": "2.0"},
    )
    train_baseline_model(
        "XAUUSD",
        "M5",
        "logistic",
        base_dir=tmp,
        params={"max_iter": 200},
    )


class TestChronology(unittest.TestCase):
    def test_walk_forward_keeps_chronology(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_walk_forward(
                "XAUUSD",
                "M5",
                "logistic",
                base_dir=tmp,
                min_train_rows=50,
                val_window_rows=25,
                save=False,
            )
            self.assertGreater(len(report.windows), 0)
            for i, w in enumerate(report.windows):
                if i > 0:
                    self.assertGreater(w.train_rows, report.windows[i - 1].train_rows)

    def test_no_random_shuffle_in_dataset_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df1, _ = load_resolved_dataset("XAUUSD", "M5", tmp)
            df2, _ = load_resolved_dataset("XAUUSD", "M5", tmp)
            pd.testing.assert_frame_equal(df1, df2)
            if "timestamp" in df1.columns:
                ts = pd.to_datetime(df1["timestamp"])
                self.assertTrue(ts.is_monotonic_increasing)

    def test_cross_validation_no_shuffle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_cross_validation(
                "XAUUSD",
                "M5",
                "logistic",
                mode="expanding",
                base_dir=tmp,
                n_folds=3,
                min_train_rows=50,
                save=False,
            )
            self.assertEqual(report.mode, "expanding")
            self.assertGreater(len(report.folds), 0)

    def test_cross_validation_blocked_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_cross_validation(
                "XAUUSD",
                "M5",
                "logistic",
                mode="blocked",
                base_dir=tmp,
                n_folds=3,
                train_block=50,
                val_block=25,
                save=True,
            )
            self.assertEqual(report.mode, "blocked")
            path = reports_dir(tmp) / "cross_validation_report.json"
            self.assertTrue(path.is_file())
            self.assertIn("expected_R", report.average_metrics)


class TestCalibration(unittest.TestCase):
    def test_calibration_output_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_calibration("XAUUSD", "M5", "logistic", base_dir=tmp, save=True)
            self.assertIn("brier_score", report.to_dict())
            self.assertGreater(len(report.reliability_curve), 0)
            path = reports_dir(tmp) / "calibration_report.json"
            self.assertTrue(path.is_file())


class TestThresholdOptimizer(unittest.TestCase):
    def test_threshold_optimizer_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = optimize_threshold("XAUUSD", "M5", "logistic", base_dir=tmp, save=True)
            self.assertIn(result.best_threshold, (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80))
            self.assertGreaterEqual(result.signals, 0)
            path = reports_dir(tmp) / "optimal_threshold.json"
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("best_threshold", payload)


class TestTradingSimulator(unittest.TestCase):
    def test_simulator_respects_tp_sl_r(self):
        y_true = np.array([1, 0, 1, 0])
        proba = np.array([0.9, 0.8, 0.2, 0.1])
        returns, take = simulate_trades(y_true, proba, threshold=0.5)
        self.assertEqual(len(returns), 2)
        np.testing.assert_array_equal(returns, [TP_R, -SL_R])
        self.assertEqual(int(take.sum()), 2)

    def test_simulator_win_loss_counts(self):
        y_true = np.array([1, 1, 0])
        proba = np.array([0.9, 0.6, 0.7])
        returns, _ = simulate_trades(y_true, proba, threshold=0.5)
        self.assertEqual(float(returns.sum()), TP_R + TP_R - SL_R)


class TestRegime(unittest.TestCase):
    def test_regime_split_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_regime_analysis(
                "XAUUSD",
                "M5",
                "logistic",
                base_dir=tmp,
                save=True,
            )
            self.assertIn("trend", report.regimes)
            self.assertIn("range", report.regimes)
            path = reports_dir(tmp) / "regime_performance.json"
            self.assertTrue(path.is_file())


class TestFeatureAblation(unittest.TestCase):
    def test_feature_ablation_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_feature_ablation(
                "XAUUSD",
                "M5",
                "logistic",
                base_dir=tmp,
                model_params={"max_iter": 100},
                save=True,
            )
            self.assertGreater(len(report.ablations), 0)
            path = reports_dir(tmp) / "feature_ablation.json"
            self.assertTrue(path.is_file())


class TestRobustness(unittest.TestCase):
    def test_robustness_report_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            report = run_robustness_tests("XAUUSD", "M5", "logistic", base_dir=tmp, save=True)
            self.assertGreater(len(report.conditions), 0)
            path = reports_dir(tmp) / "robustness_report.json"
            self.assertTrue(path.is_file())


class TestUnifiedReport(unittest.TestCase):
    def test_reports_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            summary = run_full_validation(
                "XAUUSD",
                "M5",
                "logistic",
                base_dir=tmp,
                model_params={"max_iter": 100},
                save=True,
            )
            path = reports_dir(tmp) / "model_validation_summary.json"
            self.assertTrue(path.is_file())
            self.assertIn("walk_forward", summary.to_dict())
            self.assertIn("trading_simulation", summary.to_dict())
            wf_path = reports_dir(tmp) / "walk_forward_logistic.json"
            self.assertTrue(wf_path.is_file())


class TestKernelUntouched(unittest.TestCase):
    def test_trading_kernel_import_unchanged(self):
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401

    def test_risk_gate_import_unchanged(self):
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401

    def test_execution_import_unchanged(self):
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter  # noqa: F401


if __name__ == "__main__":
    unittest.main()
