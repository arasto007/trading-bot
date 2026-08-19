"""Phase 8.6 production training pipeline tests (offline only)."""

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

from tradingbot.ml.data.paths import training_report_path, training_scaler_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.data_loader import (
    assert_no_test_leakage,
    batch_iterator,
    filter_resolved_labels,
    load_dataset_v2_splits,
    resolve_feature_columns,
)
from tradingbot.ml.training.evaluation import (
    TrainingEvaluator,
    expected_r_from_proba,
    label_r_outcomes,
    max_drawdown_proxy,
    profit_factor,
)
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import create_training_model
from tradingbot.ml.training.model_registry import ModelBundle, load_model_bundle, next_version, save_model_bundle
from tradingbot.ml.training.trainer import ProductionTrainer

try:
    import xgboost  # noqa: F401

    HAS_XGB = True
except ImportError:
    HAS_XGB = False

TRAINING_PKG = ROOT / "tradingbot" / "ml" / "training"
PHASE86_FILES = (
    "trainer.py",
    "model_factory.py",
    "data_loader.py",
    "evaluation.py",
    "feature_pipeline.py",
    "model_registry.py",
    "train_state.py",
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
        path = TRAINING_PKG / name
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
        "risk_unit": rng.uniform(1, 5, n),
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


def _store_training_v2(tmp: str, n: int = 1100, seed: int = 42) -> pd.DataFrame:
    source = _synthetic_source(n, seed=seed)
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", source)
    ProductionDatasetV2Builder(
        "XAUUSD",
        base_dir=tmp,
        min_samples=TEST_MIN_SAMPLES,
    ).build_v2()
    df = store.load_v2("XAUUSD", "M5")
    assert df is not None
    return df


class TestDatasetLoader(unittest.TestCase):
    def test_load_v2_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            self.assertGreater(len(splits.train), 0)
            self.assertGreater(len(splits.validation), 0)
            self.assertGreater(len(splits.test), 0)
            X, y = splits.train_xy()
            self.assertEqual(len(X.columns), len(feature_names()))
            self.assertTrue(set(y).issubset({0, 1}))

    def test_feature_order_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _store_training_v2(tmp)
            cols = resolve_feature_columns(df)
            self.assertEqual(cols, feature_names())

    def test_no_test_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            assert_no_test_leakage(splits)

    def test_invalid_dataset_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_dataset_v2_splits("XAUUSD", "M5", tmp)

    def test_empty_after_filter_rejected(self):
        df = _synthetic_source(50)
        df["label"] = -1
        with self.assertRaises(ValueError):
            filter_resolved_labels(df)


class TestFeaturePipeline(unittest.TestCase):
    def test_fit_transform_and_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_train, _ = splits.train_xy()
            X_val, _ = splits.validation_xy()
            X_test, _ = splits.test_xy()
            pipe = FeaturePipeline.from_registry()
            tr, va, te = pipe.fit_transform_train(X_train, X_val, X_test)
            self.assertEqual(tr.shape[1], len(feature_names()))
            pipe.save("1", tmp)
            loaded = FeaturePipeline.load("1", tmp)
            self.assertEqual(loaded.feature_order, pipe.feature_order)

    def test_empty_feature_column_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_train, _ = splits.train_xy()
            X_train = X_train.copy()
            X_train["atr_14"] = np.nan
            pipe = FeaturePipeline.from_registry()
            with self.assertRaises(ValueError):
                pipe.fit(X_train)


class TestTrainingDeterminism(unittest.TestCase):
    def test_same_seed_same_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, seed=11)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_train, y_train = splits.train_xy()
            X_val, _ = splits.validation_xy()
            X_test, _ = splits.test_xy()
            pipe = FeaturePipeline.from_registry()
            X_s, _, _ = pipe.fit_transform_train(X_train, X_val, X_test)
            m1 = create_training_model("logistic", seed=42)
            m2 = create_training_model("logistic", seed=42)
            y = y_train.to_numpy()
            m1.fit(X_s, y)
            m2.fit(X_s, y)
            X_test_s = pipe.transform(X_test)
            np.testing.assert_array_equal(m1.predict(X_test_s), m2.predict(X_test_s))


class TestMetrics(unittest.TestCase):
    def test_metric_calculation(self):
        y_true = np.array([1, 0, 1, 0])
        proba = np.array([[0.2, 0.8], [0.7, 0.3], [0.4, 0.6], [0.55, 0.45]])
        exp_r = expected_r_from_proba(proba)
        self.assertAlmostEqual(exp_r[0], 1.4, places=4)
        outcomes = label_r_outcomes(y_true)
        self.assertAlmostEqual(profit_factor(outcomes), 2.0, places=4)
        self.assertGreaterEqual(max_drawdown_proxy(outcomes), 0.0)

    def test_evaluator_outputs_required_fields(self):
        X = np.random.default_rng(0).normal(size=(40, 5))
        y = np.array([0, 1] * 20)
        model = create_training_model("logistic", seed=42)
        model.fit(X, y)
        metrics = TrainingEvaluator().evaluate(model, X, y, split="test")
        for key in ("accuracy", "precision", "recall", "f1", "roc_auc"):
            self.assertIn(key, metrics.classification)
        for key in ("win_rate", "expectancy_R", "profit_factor", "max_drawdown_proxy"):
            self.assertIn(key, metrics.trading)


class TestModelRegistry(unittest.TestCase):
    def test_save_load_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_train, y_train = splits.train_xy()
            X_val, _ = splits.validation_xy()
            X_test, _ = splits.test_xy()
            pipe = FeaturePipeline.from_registry()
            X_s = pipe.fit_transform_train(X_train, X_val, X_test)[0]
            model = create_training_model("logistic", seed=42)
            model.fit(X_s, y_train.to_numpy())
            ver = next_version(tmp)
            bundle = ModelBundle(version=ver, model=model, feature_pipeline=pipe, metadata={"test": True})
            paths = save_model_bundle(bundle, base_dir=tmp)
            self.assertTrue(paths["model"].is_file())
            self.assertTrue(training_scaler_path(ver, tmp).is_file())
            loaded = load_model_bundle(ver, tmp)
            preds = loaded.model.predict(X_s)
            self.assertEqual(len(preds), len(y_train))


class TestProductionTrainer(unittest.TestCase):
    def test_full_pipeline_trains_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, n=1100)
            result = ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
                model="all",
            )
            self.assertFalse(result.blocked, msg=result.block_reason)
            self.assertGreaterEqual(len(result.models), 2)
            if HAS_XGB:
                self.assertGreaterEqual(len(result.models), 3)
            report_path = training_report_path(result.version, tmp)
            self.assertTrue(report_path.is_file())
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIn("evaluations", payload)
            for name in result.models:
                self.assertIn(name, payload["evaluations"])

    def test_evaluate_existing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, n=1100)
            run = ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
                model="logistic",
            )
            self.assertFalse(run.blocked)
            eval_result = ProductionTrainer(base_dir=tmp).evaluate_existing(
                f"model_v{run.version}.pkl",
                "XAUUSD",
                "M5",
            )
            self.assertIn("validation", eval_result["splits"])
            self.assertIn("test", eval_result["splits"])

    def test_blocked_on_bad_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_source(30)
            DatasetStore(tmp).store_v2("XAUUSD", "M5", df)
            result = ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
                model="logistic",
            )
            self.assertTrue(result.blocked)

    def test_batch_iterator(self):
        X = np.arange(20).reshape(10, 2)
        y = np.arange(10)
        batches = list(batch_iterator(X, y, batch_size=3, shuffle=False))
        self.assertEqual(sum(len(b[0]) for b in batches), 10)


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE86_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
