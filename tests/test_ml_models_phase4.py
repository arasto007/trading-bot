"""Phase 4.0 baseline ML training framework tests."""

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

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry import feature_names
from tradingbot.ml.models.artifacts import model_metadata_path, models_registry_path
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.evaluator import ModelEvaluator, expected_r_from_proba
from tradingbot.ml.models.registry import get_model_entry, load_registry
from tradingbot.ml.models.training import create_model, load_model, train_baseline_model

try:
    import xgboost  # noqa: F401

    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    import lightgbm  # noqa: F401

    HAS_LGB = True
except ImportError:
    HAS_LGB = False


def _make_dataset(n: int = 180, seed: int = 42) -> pd.DataFrame:
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
    # Make label slightly predictable from one feature
    row["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.1, n)
    return pd.DataFrame(row)


def _store_dataset(tmp: str) -> None:
    store = DatasetStore(tmp)
    df = _make_dataset()
    store.store("XAUUSD", "M5", df)
    store.save_build_manifest(
        "XAUUSD",
        "M5",
        {
            "dataset_hash": "testhash123",
            "feature_version": "2.0",
        },
    )


class TestDatasetLoader(unittest.TestCase):
    def test_dataset_loader_respects_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            splits = load_dataset_splits("XAUUSD", "M5", tmp)
            self.assertGreater(len(splits.train), 0)
            self.assertGreater(len(splits.validation), 0)
            self.assertGreater(len(splits.test), 0)
            self.assertTrue(set(splits.train["label"]).issubset({0, 1}))
            self.assertNotIn("purge", splits.train["split"].unique())
            self.assertEqual(len(splits.feature_columns), len(feature_names()))


class TestLogisticModel(unittest.TestCase):
    def test_logistic_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            splits = load_dataset_splits("XAUUSD", "M5", tmp)
            model = create_model("logistic", {"max_iter": 500})
            model.fit(splits.X_train, splits.y_train)
            preds = model.predict(splits.X_test)
            self.assertEqual(len(preds), len(splits.X_test))

    def test_model_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            splits = load_dataset_splits("XAUUSD", "M5", tmp)
            model = create_model("logistic", {"max_iter": 300})
            model.fit(splits.X_train, splits.y_train)
            from tradingbot.ml.models.artifacts import ensure_model_dirs

            d = ensure_model_dirs("logistic", tmp)
            model.save(d)
            loaded = load_model("logistic", tmp)
            np.testing.assert_array_equal(model.predict(splits.X_test), loaded.predict(splits.X_test))


@unittest.skipUnless(HAS_XGB, "xgboost not installed")
class TestXGBoostModel(unittest.TestCase):
    def test_xgboost_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            splits = load_dataset_splits("XAUUSD", "M5", tmp)
            model = create_model("xgboost", {"n_estimators": 20, "max_depth": 3})
            model.fit(splits.X_train, splits.y_train, eval_set=(splits.X_val, splits.y_val))
            proba = model.predict_proba(splits.X_test)
            self.assertEqual(proba.shape[1], 2)
            imp = model.feature_importances()
            self.assertGreater(len(imp), 0)


@unittest.skipUnless(HAS_LGB, "lightgbm not installed")
class TestLightGBMModel(unittest.TestCase):
    def test_lightgbm_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            splits = load_dataset_splits("XAUUSD", "M5", tmp)
            model = create_model("lightgbm", {"n_estimators": 20, "num_leaves": 15})
            model.fit(splits.X_train, splits.y_train)
            self.assertEqual(len(model.predict(splits.X_test)), len(splits.X_test))


class TestEvaluator(unittest.TestCase):
    def test_evaluator_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            splits = load_dataset_splits("XAUUSD", "M5", tmp)
            model = create_model("logistic", {"max_iter": 300})
            model.fit(splits.X_train, splits.y_train)
            result = ModelEvaluator().evaluate(
                model, splits.X_test, splits.y_test, split="test"
            )
            for key in ("accuracy", "precision", "recall", "f1", "roc_auc"):
                self.assertIn(key, result.metrics)

    def test_expected_R_calculation(self):
        proba = np.array([[0.3, 0.7], [0.6, 0.4], [0.5, 0.5]])
        exp_r = expected_r_from_proba(proba)
        np.testing.assert_allclose(exp_r, [1.1, 0.2, 0.5])


class TestRegistry(unittest.TestCase):
    def test_registry_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            result = train_baseline_model(
                "XAUUSD",
                "M5",
                "logistic",
                base_dir=tmp,
                params={"max_iter": 200},
            )
            self.assertTrue(Path(result["artifact_dir"]).is_file() or Path(result["artifact_dir"]).is_dir())
            reg_path = models_registry_path(tmp)
            self.assertTrue(reg_path.is_file())
            entry = get_model_entry("logistic", "1.0", tmp)
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry["dataset_hash"], "testhash123")

    def test_dataset_hash_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_dataset(tmp)
            train_baseline_model("XAUUSD", "M5", "logistic", base_dir=tmp, params={"max_iter": 200})
            meta = json.loads(model_metadata_path("logistic", tmp).read_text(encoding="utf-8"))
            self.assertEqual(meta["dataset_hash"], "testhash123")
            self.assertIn("training_timestamp_utc", meta)


class TestKernelUntouched(unittest.TestCase):
    def test_import_kernel_risk_execution(self):
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter  # noqa: F401
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401


if __name__ == "__main__":
    unittest.main()
