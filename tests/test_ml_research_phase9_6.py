"""Phase 9.6 regime & robust signal optimization tests (offline only)."""

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
    phase9_6_optimization_report_path,
    production_best_model_path,
    regime_optimization_datasets_root,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.deep_audit import deep_audit_report_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, Label
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.regime_optimization.event_filter_optimizer import run_event_filter_optimization
from tradingbot.ml.research.regime_optimization.optimization_orchestrator import RegimeOptimizationOrchestrator
from tradingbot.ml.research.regime_optimization.regime_detector import run_regime_analysis
from tradingbot.ml.research.regime_optimization.regime_utils import (
    EVENT_SCHEMES,
    apply_event_filter,
    assign_market_regime,
    metrics_block,
    trading_metrics_from_labels,
)
from tradingbot.ml.research.regime_optimization.stable_feature_selector import run_feature_stability_selection
from tradingbot.ml.research.regime_optimization.walk_forward_validator import (
    build_walk_forward_windows,
    run_walk_forward_validation,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.training.data_loader import assert_no_test_leakage, filter_resolved_labels, load_dataset_v2_splits
from tradingbot.ml.training.phase9_production import Phase92ProductionTrainer

try:
    import lightgbm  # noqa: F401
    import xgboost  # noqa: F401

    HAS_BOOSTERS = True
except ImportError:
    HAS_BOOSTERS = False

REGIME_PKG = ROOT / "tradingbot" / "ml" / "research" / "regime_optimization"
PHASE96_FILES = (
    "regime_utils.py",
    "regime_detector.py",
    "event_filter_optimizer.py",
    "stable_feature_selector.py",
    "walk_forward_validator.py",
    "regime_model_optimizer.py",
    "optimization_orchestrator.py",
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


def _scan_package() -> list[str]:
    violations: list[str] = []
    for name in PHASE96_FILES:
        path = REGIME_PKG / name
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


def _synthetic_source(n: int = 2800, *, seed: int = 42, start_year: int = 2021) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{start_year}-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1], size=n, p=[0.48, 0.52])
    events = rng.choice(
        ["order_block", "choch", "fvg", "liquidity_sweep", "bos", "session_transition"],
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
        "atr_percentile": rng.uniform(5, 95, n),
        "ema_cross_state": rng.choice([-1.0, 0.0, 1.0], size=n),
        "ema50_slope": rng.normal(0, 0.5, n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    rows["spread_spike"] = 0.0
    return pd.DataFrame(rows)


def _write_candles(tmp: str, n: int = 3000) -> None:
    ts = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
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


def _write_reports(tmp: str) -> None:
    reports = Path(tmp) / "ml" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "training_comparison_report.json").write_text(
        json.dumps(
            {
                "best_model": "logistic",
                "evaluations": {
                    "logistic": {
                        "validation": {"classification": {"roc_auc": 0.35}},
                        "test": {"classification": {"roc_auc": 0.35}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (reports / "phase9_4_retraining_report.json").write_text(
        json.dumps({"summary": {"validation_roc_auc": 0.40}}),
        encoding="utf-8",
    )
    (reports / "phase9_5_discovery_report.json").write_text(
        json.dumps({"model_findings": {"validation_roc_auc": 0.42}}),
        encoding="utf-8",
    )
    (reports / "model_optimization_report.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model": "lightgbm",
                        "best_params": {
                            "learning_rate": 0.05,
                            "n_estimators": 40,
                            "max_depth": 3,
                            "num_leaves": 15,
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_deep_audit(tmp: str) -> None:
    p = deep_audit_report_path(tmp)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"status": "pass"}), encoding="utf-8")


def _setup(tmp: str, n: int = 2800) -> str:
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", _synthetic_source(n))
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    _write_candles(tmp, n + 200)
    _write_deep_audit(tmp)
    _write_reports(tmp)
    Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run("XAUUSD", "M5")
    return dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))


@unittest.skipUnless(HAS_BOOSTERS, "xgboost and lightgbm required")
class TestPhase96RegimeOptimization(unittest.TestCase):
    def test_dataset_v2_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup(tmp)
            RegimeOptimizationOrchestrator(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_no_production_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            model_path = production_best_model_path(tmp)
            model_mtime_before = model_path.stat().st_mtime if model_path.is_file() else None
            RegimeOptimizationOrchestrator(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            if model_mtime_before is not None:
                self.assertEqual(model_path.stat().st_mtime, model_mtime_before)

    def test_no_kernel_imports(self):
        violations = [v for v in _scan_package() if "kernel" in v]
        self.assertEqual(violations, [])

    def test_no_risk_imports(self):
        violations = [v for v in _scan_package() if "risk" in v.lower()]
        self.assertEqual(violations, [])

    def test_no_execution_imports(self):
        violations = [v for v in _scan_package() if "execution" in v]
        self.assertEqual(violations, [])

    def test_no_mt5_usage(self):
        violations = [v for v in _scan_package() if "MetaTrader5" in v or "mt5" in v.lower()]
        self.assertEqual(violations, [])

    def test_regime_detector_deterministic(self):
        df = _synthetic_source(200, seed=11)
        a = assign_market_regime(df)
        b = assign_market_regime(df)
        pd.testing.assert_series_equal(a, b)

    def test_no_future_leakage(self):
        df = _synthetic_source(100, seed=3)
        forbidden = {"label", "tp_hit", "sl_hit", "mfe", "mae", "future_return", "future_window_bars"}
        source = (REGIME_PKG / "regime_utils.py").read_text(encoding="utf-8")
        for col in forbidden:
            self.assertNotIn(f'"{col}"', source.split("assign_market_regime")[1].split("def apply_event")[0])

    def test_event_filtering_correctness(self):
        df = _synthetic_source(300, seed=5)
        filtered = apply_event_filter(df, "B_order_block_only")
        self.assertTrue(filtered["event_type"].isin(["order_block"]).all())
        report = run_event_filter_optimization(df)
        self.assertEqual(len(report["results"]), len(EVENT_SCHEMES))

    def test_feature_stability_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            report = run_feature_stability_selection(splits, seed=42)
            self.assertGreater(len(report["features"]), 0)
            self.assertIn("A_top10_stable", report["feature_sets"])

    def test_unstable_features_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            report = run_feature_stability_selection(splits, seed=42)
            set_c = report["feature_sets"]["C_all_except_unstable"]
            for feat in report["unstable_features"]:
                self.assertNotIn(feat, set_c)

    def test_walk_forward_chronological_integrity(self):
        df = filter_resolved_labels(_synthetic_source(1200, start_year=2021))
        windows = build_walk_forward_windows(df)
        self.assertGreater(len(windows), 0)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        for window in windows:
            if "index_splits" in window:
                continue
            tr_s, tr_e = window["train_years"]
            va_s, va_e = window["validation_years"]
            te_s, te_e = window["test_years"]
            self.assertLessEqual(tr_e, va_s)
            self.assertLessEqual(va_e, te_s)

    def test_no_shuffle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            report = run_walk_forward_validation(df, feature_names()[:10], seed=42)
            self.assertFalse(report["shuffle"])
            for window in report["windows"]:
                if not window.get("skipped"):
                    self.assertFalse(window.get("shuffle", True))

    def test_model_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            X, y = splits.train_xy()
            cols = splits.feature_columns[:10]
            Xv = X.loc[:, cols].astype(np.float64).values
            yv = y.to_numpy(dtype=int)
            m1 = create_research_model("logistic", 42)
            m2 = create_research_model("logistic", 42)
            m1.fit(Xv, yv)
            m2.fit(Xv, yv)
            np.testing.assert_array_equal(m1.predict(Xv), m2.predict(Xv))

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = RegimeOptimizationOrchestrator(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            path = phase9_6_optimization_report_path(tmp)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "9.6")
            self.assertIn("recommendation", payload)
            self.assertIn("best_configuration", payload)

    def test_experimental_dataset_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            RegimeOptimizationOrchestrator(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            root = regime_optimization_datasets_root(tmp)
            self.assertTrue(root.is_dir())
            prod_v2 = DatasetStore(tmp).resolve_v2_path("XAUUSD", "M5")
            for exp in root.glob("*.parquet"):
                self.assertNotEqual(exp.resolve(), prod_v2.resolve())

    def test_metrics_calculation(self):
        y = np.array([int(Label.TP_FIRST), int(Label.SL_FIRST), int(Label.TP_FIRST)])
        pred = np.array([1, 0, 1])
        proba = np.array([[0.2, 0.8], [0.7, 0.3], [0.4, 0.6]])
        block = metrics_block(y, pred, proba)
        self.assertIn("classification", block)
        self.assertIn("trading", block)
        tm = trading_metrics_from_labels(y)
        self.assertGreater(tm["win_rate"], 0.0)

    def test_full_offline_orchestrator_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = RegimeOptimizationOrchestrator(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            self.assertEqual(result.status, "PASS")
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            assert_no_test_leakage(splits)
            report = run_regime_analysis(filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5")))
            self.assertGreater(len(report["by_regime"]), 0)


if __name__ == "__main__":
    unittest.main()
