"""Phase 9.8 walk-forward validation tests (offline only)."""

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

from tradingbot.ml.backtest.model_loader import build_phase9_6_artifacts, load_phase9_6_bundle, verify_integrity
from tradingbot.ml.data.paths import (
    phase9_6_optimization_report_path,
    phase9_8_robustness_report_path,
    phase9_8_walk_forward_report_path,
    phase9_8_window_results_path,
    regime_optimization_dataset_path,
)
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.research.walk_forward.model_validator import _ml_metrics, _simulate_trades, validate_window
from tradingbot.ml.research.walk_forward.robustness_analyzer import analyze_robustness, compute_robustness_score
from tradingbot.ml.research.walk_forward.walk_forward_engine import WalkForwardEngine
from tradingbot.ml.research.walk_forward.walk_forward_metrics import aggregate_window_metrics
from tradingbot.ml.research.walk_forward.window_manager import (
    WalkForwardWindow,
    assert_chronological,
    assert_no_overlap,
    build_rolling_index_windows,
    build_standard_windows,
    partition_window,
)
from tradingbot.ml.training.data_loader import filter_resolved_labels

try:
    import xgboost  # noqa: F401

    HAS_XGB = True
except ImportError:
    HAS_XGB = False

WF_PKG = ROOT / "tradingbot" / "ml" / "research" / "walk_forward"
WF_FILES = (
    "walk_forward_engine.py",
    "window_manager.py",
    "model_validator.py",
    "walk_forward_metrics.py",
    "robustness_analyzer.py",
    "report_generator.py",
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
STABLE_FEATURES = ("ema50_slope", "candle_direction", "structure_distance", "ema_cross_state")
TEST_MIN = 80


def _scan_package() -> list[str]:
    violations: list[str] = []
    for name in WF_FILES:
        tree = ast.parse((WF_PKG / name).read_text(encoding="utf-8"))
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


def _multi_year_source(n_per_year: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames: list[pd.DataFrame] = []
    for year in range(2021, 2027):
        n = n_per_year
        ts = pd.date_range(f"{year}-01-01", periods=n, freq="5min", tz="UTC")
        labels = rng.choice([0, 1], size=n, p=[0.48, 0.52])
        rows: dict[str, object] = {
            "timestamp": ts,
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "event_type": rng.choice(["order_block", "choch", "fvg", "bos"], size=n),
            "event_time": ts,
            "event_id": [f"{year}_{i}" for i in range(n)],
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
        frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True)


def _write_phase96_report(tmp: str, fingerprint: str) -> None:
    report = {
        "phase": "9.6",
        "dataset": {"fingerprint": fingerprint},
        "best_configuration": {
            "regime": "RANGE",
            "event_filter": "A_all_events",
            "feature_set": "A_top10_stable",
            "model": "logistic",
        },
        "feature_findings": {"feature_sets": {"A_top10_stable": list(STABLE_FEATURES)}},
        "model_optimization": {
            "best_candidate": {
                "variant_id": "RANGE__A_all_events__A_top10_stable",
                "hyperparameters": {},
            }
        },
    }
    path = phase9_6_optimization_report_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


def _setup(tmp: str) -> str:
    store = DatasetStore(tmp)
    raw = _multi_year_source(180)
    store.store("XAUUSD", "M5", raw)
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN).build_v2()
    v2 = store.load_v2("XAUUSD", "M5")
    assert v2 is not None
    fp = dataset_content_fingerprint(v2)
    _write_phase96_report(tmp, fp)
    resolved = filter_resolved_labels(v2)
    resolved["market_regime"] = assign_market_regime(resolved)
    range_df = resolved.copy()
    range_df["trend_strength"] = 15.0
    range_df["atr_percentile"] = 45.0
    range_df["volatility_regime"] = 0.5
    path = regime_optimization_dataset_path("XAUUSD", "M5", "RANGE__A_all_events__A_top10_stable", tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    range_df.to_parquet(path, index=False)
    build_phase9_6_artifacts("XAUUSD", "M5", base_dir=tmp, seed=42)
    return fp


@unittest.skipUnless(HAS_XGB, "xgboost required")
class TestPhase98WalkForward(unittest.TestCase):
    def test_window_generation(self):
        df = _multi_year_source(150)
        windows = build_standard_windows(df)
        self.assertGreaterEqual(len(windows), 4)

    def test_chronological_ordering(self):
        df = _multi_year_source(100).sort_values("timestamp")
        assert_chronological(df)

    def test_no_overlap_train_validation(self):
        df = _multi_year_source(120)
        for w in build_standard_windows(df):
            train, val = partition_window(df, w)
            assert_no_overlap(train, val)

    def test_no_future_leakage_partition(self):
        df = _multi_year_source(100)
        w = build_standard_windows(df)[0]
        train, val = partition_window(df, w)
        train_max = pd.to_datetime(train["timestamp"], utc=True).max()
        val_min = pd.to_datetime(val["timestamp"], utc=True).min()
        self.assertGreater(val_min, train_max)

    def test_scaler_train_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            windows = build_standard_windows(df)
            w = windows[0]
            train, val = partition_window(df, w)
            bundle = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            result = validate_window(
                train, val, w,
                feature_cols=bundle.feature_order,
                model_name="logistic",
                hyperparameters={},
                seed=42,
            )
            self.assertFalse(result.get("skipped", True))
            self.assertEqual(result.get("scaler_fit_on"), "train_only")

    def test_model_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            bundle = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            self.assertEqual(bundle.configuration["regime"], "RANGE")

    def test_dataset_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup(tmp)
            WalkForwardEngine(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_feature_order_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            b1 = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            b2 = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            self.assertEqual(b1.feature_order, b2.feature_order)

    def test_prediction_determinism(self):
        rng = np.random.default_rng(42)
        X = rng.normal(0, 1, (40, 4))
        y = rng.choice([0, 1], size=40)
        m1 = create_research_model("logistic", 42)
        m2 = create_research_model("logistic", 42)
        m1.fit(X, y)
        m2.fit(X, y)
        np.testing.assert_array_equal(m1.predict(X), m2.predict(X))

    def test_metric_calculation(self):
        y = np.array([1, 0, 1, 0])
        pred = np.array([1, 0, 0, 0])
        proba = np.array([[0.2, 0.8], [0.7, 0.3], [0.6, 0.4], [0.5, 0.5]])
        m = _ml_metrics(y, pred, proba)
        self.assertIn("roc_auc", m)
        self.assertIn("f1", m)

    def test_empty_window_handling(self):
        empty = pd.DataFrame(columns=["timestamp", "label"])
        w = WalkForwardWindow("w0", "", "", "", "", (2021, 2021), (2022, 2022))
        result = validate_window(empty, empty, w, feature_cols=list(STABLE_FEATURES), model_name="logistic", hyperparameters={})
        self.assertTrue(result.get("skipped"))

    def test_small_dataset_handling(self):
        df = _multi_year_source(30)
        windows = build_standard_windows(df)
        self.assertGreater(len(windows), 0)

    def test_rolling_window_correctness(self):
        df = _multi_year_source(80)
        windows = build_rolling_index_windows(df, n_windows=4)
        self.assertGreater(len(windows), 0)
        for w in windows:
            self.assertEqual(w.mode, "rolling")

    def test_expanding_window_correctness(self):
        df = _multi_year_source(120)
        windows = build_standard_windows(df)
        expanding = [w for w in windows if w.mode == "expanding"]
        self.assertGreater(len(expanding), 0)

    def test_trade_simulation_consistency(self):
        n = 20
        df = pd.DataFrame({
            "direction": [1] * n,
            "risk_unit": [5.0] * n,
            "entry_price": [2300.0] * n,
            "stop_loss": [2290.0] * n,
            "take_profit": [2320.0] * n,
            "label": [1, 0] * (n // 2),
            "atr_14": [5.0] * n,
        })
        proba = np.tile([0.3, 0.7], (n, 1))
        t1 = _simulate_trades(df, proba)
        t2 = _simulate_trades(df, proba)
        self.assertEqual(t1["num_trades"], t2["num_trades"])

    def test_drawdown_calculation(self):
        n = 10
        df = pd.DataFrame({
            "direction": [1] * n, "risk_unit": [5.0] * n,
            "entry_price": [2300.0] * n, "stop_loss": [2290.0] * n,
            "take_profit": [2320.0] * n, "label": [0] * n, "atr_14": [5.0] * n,
        })
        proba = np.tile([0.3, 0.7], (n, 1))
        m = _simulate_trades(df, proba)
        self.assertGreaterEqual(m["max_drawdown"], 0.0)

    def test_profit_factor_calculation(self):
        windows = [{"profit_factor": 1.5, "expectancy": 0.2, "win_rate": 0.5, "roc_auc": 0.55, "num_trades": 10}]
        agg = aggregate_window_metrics(windows)
        self.assertAlmostEqual(agg["mean_metrics"]["profit_factor"], 1.5)

    def test_robustness_score_calculation(self):
        windows = [
            {"profit_factor": 1.3, "expectancy": 0.1, "train_val_auc_gap": 0.02},
            {"profit_factor": 1.1, "expectancy": 0.05, "train_val_auc_gap": 0.03},
        ]
        agg = aggregate_window_metrics(windows)
        score = compute_robustness_score(windows, agg)
        self.assertGreater(score, 0.0)
        analysis = analyze_robustness(windows, agg)
        self.assertIn(analysis["overfitting_risk"], ("LOW", "MEDIUM", "HIGH"))

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = WalkForwardEngine(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            self.assertTrue(phase9_8_walk_forward_report_path(tmp).is_file())
            self.assertTrue(phase9_8_window_results_path(tmp).is_file())
            self.assertTrue(phase9_8_robustness_report_path(tmp).is_file())

    def test_forbidden_imports_ast_scan(self):
        self.assertEqual(_scan_package(), [])

    def test_integrity_on_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            bundle = load_phase9_6_bundle(base_dir=tmp, build_if_missing=False)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            self.assertTrue(verify_integrity(bundle, df).passed)


if __name__ == "__main__":
    unittest.main()
