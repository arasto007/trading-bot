"""Phase 9.4 research retraining tests (offline only)."""

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
    experimental_dataset_path,
    phase9_4_retraining_report_path,
    research_datasets_root,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.deep_audit import deep_audit_report_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.model_selection import ModelCandidate, ModelSelector
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.retrain_optimizer import (
    DATASET_VARIANTS,
    Phase94RetrainOptimizer,
    ResearchScaler,
    _select_features,
    _zero_variance_features,
    build_experimental_dataset,
    create_research_model,
    splits_from_frame,
)
from tradingbot.ml.training.data_loader import assert_no_test_leakage
from tradingbot.ml.training.evaluation import TrainingEvaluator
from tradingbot.ml.training.phase9_production import Phase92ProductionTrainer

try:
    import lightgbm  # noqa: F401
    import xgboost  # noqa: F401

    HAS_BOOSTERS = True
except ImportError:
    HAS_BOOSTERS = False

PHASE94_FILES = (
    "retrain_optimizer.py",
    "model_selection.py",
    "retrain_report.py",
)
RESEARCH_PKG = ROOT / "tradingbot" / "ml" / "research"
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
        path = RESEARCH_PKG / name
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
    events = rng.choice(
        ["order_block", "choch", "fvg", "liquidity_sweep", "session_transition", "trading_session"],
        size=n,
    )
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": events,
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
    rows["spread_spike"] = 0.0
    rows["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.05, n)
    return pd.DataFrame(rows)


def _write_candles(tmp: str, n: int = 1200) -> None:
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    close = 2300.0 + rng.normal(0, 0.5, n).cumsum()
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0.1, 1.0, n),
            "low": close - rng.uniform(0.1, 1.0, n),
            "close": close,
        },
        index=ts,
    )
    CandleStore(tmp).store("XAUUSD", "M5", df)


def _write_phase93_reports(tmp: str) -> None:
    reports = Path(tmp) / "ml" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase9_3_research_report.json").write_text(
        json.dumps({"best_features": feature_names()[:15], "best_model": "lightgbm"}),
        encoding="utf-8",
    )
    (reports / "feature_importance_report.json").write_text(
        json.dumps(
            {
                "rankings": [{"feature": f, "importance_score": 1.0, "rank": i + 1} for i, f in enumerate(feature_names()[:15])],
                "detection": {"dead_features": ["spread_spike"], "low_contribution_features": ["engulfing_flag"]},
            }
        ),
        encoding="utf-8",
    )
    (reports / "model_optimization_report.json").write_text(
        json.dumps(
            {
                "models": [
                    {"model": "lightgbm", "best_params": {"learning_rate": 0.05, "max_depth": 4, "n_estimators": 80, "num_leaves": 31}},
                    {"model": "xgboost", "best_params": {"max_depth": 5, "learning_rate": 0.08, "n_estimators": 60}},
                ]
            }
        ),
        encoding="utf-8",
    )
    (reports / "training_comparison_report.json").write_text(
        json.dumps(
            {
                "phase": "9.2",
                "best_model": "logistic",
                "evaluations": {
                    "logistic": {
                        "validation": {"classification": {"roc_auc": 0.35, "precision": 0.5, "recall": 0.1}},
                        "test": {"classification": {"roc_auc": 0.49}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_passing_deep_audit(tmp: str) -> None:
    path = deep_audit_report_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")


def _setup_env(tmp: str, *, n: int = 1100) -> str:
    source = _synthetic_source(n)
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", source)
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    _write_candles(tmp, n=n + 100)
    _write_passing_deep_audit(tmp)
    _write_phase93_reports(tmp)
    Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run("XAUUSD", "M5")
    return dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))


@unittest.skipUnless(HAS_BOOSTERS, "xgboost and lightgbm required")
class TestPhase94Retraining(unittest.TestCase):
    def test_original_dataset_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp_before = _setup_env(tmp)
            Phase94RetrainOptimizer(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_experimental_datasets_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_env(tmp)
            Phase94RetrainOptimizer(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            root = research_datasets_root(tmp)
            self.assertTrue(root.is_dir())
            exp_files = list(root.glob("*.parquet"))
            self.assertGreater(len(exp_files), 0)
            v2_path = DatasetStore(tmp).resolve_v2_path("XAUUSD", "M5")
            for exp in exp_files:
                self.assertNotEqual(exp.resolve(), v2_path.resolve())

    def test_no_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_env(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            variant = DATASET_VARIANTS[2]
            from tradingbot.ml.research.retrain_optimizer import _load_phase93_findings

            findings = _load_phase93_findings(tmp)
            exp_df, features, _ = build_experimental_dataset(df, None, variant, findings)
            splits = splits_from_frame(exp_df, features, "XAUUSD", "M5")
            assert_no_test_leakage(splits)

    def test_chronological_split_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_env(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            from tradingbot.ml.research.retrain_optimizer import _load_phase93_findings

            findings = _load_phase93_findings(tmp)
            exp_df, features, _ = build_experimental_dataset(df, None, DATASET_VARIANTS[2], findings)
            for split in ("train", "validation", "test"):
                part = exp_df.loc[exp_df["split"] == split]
                self.assertGreater(len(part), 0)

    def test_feature_selection_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_source(200)
            from tradingbot.ml.research.retrain_optimizer import _load_phase93_findings

            findings = _load_phase93_findings(tmp)
            findings["top_features"] = feature_names()[:10]
            cols = _select_features(df, findings, use_selection=True)
            self.assertLessEqual(len(cols), 10)
            self.assertNotIn("spread_spike", cols)

    def test_dead_feature_removal(self):
        df = _synthetic_source(100)
        df["spread_spike"] = 0.0
        dead = _zero_variance_features(df, list(feature_names()))
        self.assertIn("spread_spike", dead)

    def test_deterministic_training(self):
        rng = np.random.default_rng(42)
        X = rng.normal(size=(80, 10))
        y = np.array([0, 1] * 40)
        m1 = create_research_model("lightgbm", 42, {"learning_rate": 0.05, "n_estimators": 40, "max_depth": 3, "num_leaves": 15})
        m2 = create_research_model("lightgbm", 42, {"learning_rate": 0.05, "n_estimators": 40, "max_depth": 3, "num_leaves": 15})
        m1.fit(X, y)
        m2.fit(X, y)
        np.testing.assert_array_equal(m1.predict(X), m2.predict(X))

    def test_model_comparison_works(self):
        rng = np.random.default_rng(0)
        X = rng.normal(size=(60, 8))
        y = np.array([0, 1] * 30)
        m1 = create_research_model("logistic", 42)
        m2 = create_research_model("lightgbm", 42)
        m1.fit(X[:40], y[:40])
        m2.fit(X[:40], y[:40])
        ev = TrainingEvaluator()
        c1 = ModelCandidate("logistic", "t", ev.evaluate(m1, X[40:50], y[40:50], split="validation"), ev.evaluate(m1, X[50:], y[50:], split="test"))
        c2 = ModelCandidate("lightgbm", "t", ev.evaluate(m2, X[40:50], y[40:50], split="validation"), ev.evaluate(m2, X[50:], y[50:], split="test"))
        ranked = ModelSelector().rank([c1, c2])
        self.assertEqual(len(ranked), 2)
        self.assertGreater(ranked[0].composite_score, 0)

    def test_scaler_train_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_env(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            from tradingbot.ml.research.retrain_optimizer import _load_phase93_findings

            findings = _load_phase93_findings(tmp)
            exp_df, features, _ = build_experimental_dataset(df, None, DATASET_VARIANTS[2], findings)
            splits = splits_from_frame(exp_df, features, "XAUUSD", "M5")
            scaler = ResearchScaler(features)
            X_train, _ = splits.train_xy()
            scaler.fit(X_train)
            train_mean = X_train.loc[:, features].astype(float).mean().to_numpy()
            np.testing.assert_allclose(scaler.scaler.mean_, train_mean, rtol=1e-4, atol=1e-4)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_env(tmp)
            result = Phase94RetrainOptimizer(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            path = phase9_4_retraining_report_path(tmp)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "9.4")
            self.assertIn("features_used", payload)
            self.assertIn("labels_used", payload)
            self.assertIn("phase9_2_baseline", payload)
            self.assertIn("improvement_vs_phase9_2", payload)

    def test_improvement_over_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_env(tmp)
            result = Phase94RetrainOptimizer(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            report = json.loads(phase9_4_retraining_report_path(tmp).read_text(encoding="utf-8"))
            best_auc = report["best_model"]["validation_metrics"]["classification"]["roc_auc"]
            base_auc = report["phase9_2_baseline"]["validation"]["classification"]["roc_auc"]
            self.assertGreaterEqual(best_auc, base_auc)

    def test_experimental_path_naming(self):
        path = experimental_dataset_path("XAUUSD", "M5", "research_optimized", "/tmp")
        self.assertIn("exp_research_optimized", path.name)


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE94_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
