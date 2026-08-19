"""Phase 9.2 production ML training tests (offline only)."""

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
    production_best_model_path,
    production_feature_order_path,
    production_model_metadata_path,
    production_scaler_path,
    training_comparison_report_path,
)
from tradingbot.ml.dataset.deep_audit import deep_audit_report_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.data_loader import (
    assert_no_test_leakage,
    load_dataset_v2_splits,
    resolve_feature_columns,
)
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import create_training_model
from tradingbot.ml.training.phase9_production import (
    Phase92ProductionTrainer,
    load_production_bundle,
    resolve_phase9_model_list,
    run_pre_training_sanity,
)

try:
    import xgboost  # noqa: F401
    import lightgbm  # noqa: F401

    HAS_BOOSTERS = True
except ImportError:
    HAS_BOOSTERS = False

TRAINING_PKG = ROOT / "tradingbot" / "ml" / "training"
PHASE92_FILES = (
    "phase9_production.py",
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


def _write_passing_deep_audit(tmp: str, symbol: str = "XAUUSD", timeframe: str = "M5") -> None:
    path = deep_audit_report_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "phase": "9.1.5",
                "status": "pass",
                "health_score": 97.5,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@unittest.skipUnless(HAS_BOOSTERS, "xgboost and lightgbm required for Phase 9.2")
class TestPhase92Training(unittest.TestCase):
    def test_dataset_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            self.assertGreater(len(splits.train), 0)
            self.assertEqual(len(splits.feature_columns), len(feature_names()))

    def test_feature_order_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _store_training_v2(tmp)
            cols = resolve_feature_columns(df)
            self.assertEqual(cols, feature_names())

    def test_scaler_train_only_fitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_train, _ = splits.train_xy()
            X_val, _ = splits.validation_xy()
            X_test, _ = splits.test_xy()
            pipe = FeaturePipeline.from_registry()
            pipe.fit(X_train)
            train_mean = X_train.loc[:, pipe.feature_order].astype(np.float64).mean().to_numpy()
            np.testing.assert_allclose(pipe.scaler.mean_, train_mean, rtol=1e-5)
            tr = pipe.transform(X_train)
            va = pipe.transform(X_val)
            te = pipe.transform(X_test)
            self.assertEqual(tr.shape[1], len(feature_names()))
            self.assertEqual(va.shape[1], len(feature_names()))
            self.assertEqual(te.shape[1], len(feature_names()))

    def test_no_test_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            assert_no_test_leakage(splits)

    def test_deterministic_training(self):
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

    def test_full_pipeline_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, n=1100)
            _write_passing_deep_audit(tmp)
            result = Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
            )
            self.assertFalse(result.blocked, msg=result.block_reason)
            self.assertEqual(len(result.models), 4)
            self.assertTrue(production_best_model_path(tmp).is_file())
            self.assertTrue(production_scaler_path(tmp).is_file())
            self.assertTrue(production_feature_order_path(tmp).is_file())
            self.assertTrue(production_model_metadata_path(tmp).is_file())
            self.assertTrue(training_comparison_report_path(tmp).is_file())
            report = json.loads(training_comparison_report_path(tmp).read_text(encoding="utf-8"))
            self.assertEqual(report["phase"], "9.2")
            self.assertIn(report["best_model"], result.models)
            for name in result.models:
                val_cls = report["evaluations"][name]["validation"]["classification"]
                test_cls = report["evaluations"][name]["test"]["classification"]
                for key in ("accuracy", "precision", "recall", "f1", "roc_auc", "confusion_matrix"):
                    self.assertIn(key, val_cls)
                    self.assertIn(key, test_cls)
                for key in (
                    "signal_precision",
                    "tp_prediction_rate",
                    "sl_prediction_rate",
                    "expected_R_multiple",
                    "profit_factor_proxy",
                    "max_drawdown_proxy",
                ):
                    self.assertIn(key, report["evaluations"][name]["test"]["trading"])

    def test_model_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, n=1100)
            _write_passing_deep_audit(tmp)
            result = Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
            )
            self.assertFalse(result.blocked)
            model, pipeline, metadata = load_production_bundle(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X_test, y_test = splits.test_xy()
            X_test_s = pipeline.transform(X_test)
            preds = model.predict(X_test_s)
            self.assertEqual(len(preds), len(y_test))
            self.assertEqual(metadata["model_name"], result.primary_model)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, n=1100)
            _write_passing_deep_audit(tmp)
            result = Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
            )
            path = training_comparison_report_path(tmp)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["selection_criteria"], "validation_roc_auc")
            self.assertEqual(payload["seed"], 42)
            self.assertEqual(str(result.report_path), str(path))

    def test_blocked_without_deep_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _store_training_v2(tmp, n=1100)
            result = Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run(
                "XAUUSD",
                "M5",
            )
            self.assertTrue(result.blocked)
            self.assertIn("deep_audit", result.block_reason)

    def test_resolve_phase9_models(self):
        models = resolve_phase9_model_list()
        self.assertEqual(models, ["logistic", "random_forest", "xgboost", "lightgbm"])

    def test_pre_training_sanity_passes_with_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _store_training_v2(tmp)
            _write_passing_deep_audit(tmp)
            sanity = run_pre_training_sanity(df, "XAUUSD", "M5", tmp, min_samples=TEST_MIN_SAMPLES)
            self.assertTrue(sanity.passed, msg=sanity.issues)


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE92_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
