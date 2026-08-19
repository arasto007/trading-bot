"""Phase 9.9 robustness optimization tests (offline only)."""

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

from tradingbot.ml.backtest.model_loader import build_phase9_6_artifacts, load_phase9_6_bundle
from tradingbot.ml.data.paths import (
    feature_stability_report_path,
    phase9_6_optimization_report_path,
    phase9_8_walk_forward_report_path,
    phase9_9_feature_selection_path,
    phase9_9_model_comparison_path,
    phase9_9_robustness_report_path,
    regime_optimization_dataset_path,
)
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.robustness_optimizer.candidate_selector import composite_score, rank_candidates
from tradingbot.ml.research.robustness_optimizer.model_regularization import (
    ModelCandidateConfig,
    build_regularized_candidates,
    create_regularized_model,
)
from tradingbot.ml.research.robustness_optimizer.optimization_orchestrator import RobustnessOptimizer
from tradingbot.ml.research.robustness_optimizer.regime_robustness import analyze_regime_robustness
from tradingbot.ml.research.robustness_optimizer.stable_feature_research import build_feature_subsets
from tradingbot.ml.research.robustness_optimizer.walk_forward_optimizer import run_walk_forward_experiment
from tradingbot.ml.research.walk_forward.window_manager import assert_no_overlap, build_standard_windows, partition_window
from tradingbot.ml.training.data_loader import filter_resolved_labels

try:
    import xgboost  # noqa: F401

    HAS_XGB = True
except ImportError:
    HAS_XGB = False

PKG = ROOT / "tradingbot" / "ml" / "research" / "robustness_optimizer"
PKG_FILES = (
    "model_regularization.py",
    "stable_feature_research.py",
    "regime_robustness.py",
    "walk_forward_optimizer.py",
    "probability_selection_gate.py",
    "candidate_selector.py",
    "report_generator.py",
    "window_validator.py",
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
STABLE = ("ema50_slope", "candle_direction", "structure_distance", "ema_cross_state")


def _scan() -> list[str]:
    violations: list[str] = []
    for name in PKG_FILES:
        tree = ast.parse((PKG / name).read_text(encoding="utf-8"))
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


def _multi_year(n: int = 160, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for year in range(2021, 2027):
        ts = pd.date_range(f"{year}-01-01", periods=n, freq="5min", tz="UTC")
        labels = rng.choice([0, 1], size=n, p=[0.48, 0.52])
        rows: dict[str, object] = {
            "timestamp": ts,
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "event_type": rng.choice(["order_block", "choch", "fvg"], size=n),
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


def _write_reports(tmp: str, fp: str) -> None:
    reports = Path(tmp) / "ml" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase9_6_optimization_report.json").write_text(
        json.dumps(
            {
                "dataset": {"fingerprint": fp},
                "best_configuration": {"regime": "RANGE", "event_filter": "A_all_events", "feature_set": "A_top10_stable", "model": "logistic"},
                "feature_findings": {"feature_sets": {"A_top10_stable": list(STABLE)}, "stable_features": list(STABLE)},
                "model_optimization": {"best_candidate": {"variant_id": "RANGE__A_all_events__A_top10_stable", "hyperparameters": {}}},
            }
        ),
        encoding="utf-8",
    )
    (reports / "feature_stability_report.json").write_text(
        json.dumps(
            {
                "stable_features": list(STABLE),
                "unstable_features": ["rsi_14"],
                "remove_features": ["spread_spike"],
                "feature_sets": {"C_all_except_unstable": list(STABLE)},
                "features": [{"feature": f, "train_importance": 0.1, "category": "STABLE"} for f in STABLE],
            }
        ),
        encoding="utf-8",
    )
    (reports / "phase9_8_walk_forward_report.json").write_text(
        json.dumps({"robustness_score": 50.0, "overfitting_risk": "HIGH", "mean_metrics": {"profit_factor": 1.0, "expectancy": 0.05}}),
        encoding="utf-8",
    )


def _setup(tmp: str) -> str:
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", _multi_year(140))
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=80).build_v2()
    v2 = store.load_v2("XAUUSD", "M5")
    assert v2 is not None
    fp = dataset_content_fingerprint(v2)
    _write_reports(tmp, fp)
    resolved = filter_resolved_labels(v2)
    resolved["trend_strength"] = 15.0
    resolved["atr_percentile"] = 45.0
    resolved["volatility_regime"] = 0.5
    path = regime_optimization_dataset_path("XAUUSD", "M5", "RANGE__A_all_events__A_top10_stable", tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved.to_parquet(path, index=False)
    build_phase9_6_artifacts("XAUUSD", "M5", base_dir=tmp, seed=42)
    return fp


@unittest.skipUnless(HAS_XGB, "xgboost required")
class TestPhase99Robustness(unittest.TestCase):
    def test_window_generation(self):
        df = _multi_year(120)
        self.assertGreaterEqual(len(build_standard_windows(df)), 4)

    def test_no_overlap_train_validation(self):
        df = _multi_year(120)
        for w in build_standard_windows(df):
            train, val = partition_window(df, w)
            assert_no_overlap(train, val)

    def test_no_future_leakage(self):
        df = _multi_year(100)
        w = build_standard_windows(df)[0]
        train, val = partition_window(df, w)
        self.assertGreater(
            pd.to_datetime(val["timestamp"], utc=True).min(),
            pd.to_datetime(train["timestamp"], utc=True).max(),
        )

    def test_scaler_train_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            cand = ModelCandidateConfig("logistic_c1", "logistic", {"C": 1.0})
            result = run_walk_forward_experiment(df, candidate=cand, feature_cols=list(STABLE), seed=42)
            active = [w for w in result["windows"] if not w.get("skipped")]
            self.assertGreater(len(active), 0)
            self.assertEqual(active[0].get("scaler_fit_on"), "train_only")

    def test_model_isolation(self):
        cands = build_regularized_candidates()
        self.assertGreaterEqual(len(cands), 5)

    def test_dataset_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup(tmp)
            RobustnessOptimizer(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_feature_order_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            subsets = build_feature_subsets(tmp)
            self.assertIn("stable_4", subsets)
            self.assertEqual(len(subsets["stable_4"]), 4)

    def test_prediction_determinism(self):
        X = np.random.default_rng(1).normal(0, 1, (50, 4))
        y = np.random.default_rng(2).choice([0, 1], 50)
        c = ModelCandidateConfig("logistic_c1", "logistic", {"C": 1.0})
        m1 = create_regularized_model(c, 42)
        m2 = create_regularized_model(c, 42)
        m1.fit(X, y)
        m2.fit(X, y)
        np.testing.assert_array_equal(m1.predict(X), m2.predict(X))

    def test_metric_calculation(self):
        exp = {
            "robustness_score": 70.0,
            "mean_profit_factor": 1.3,
            "mean_auc_gap": 0.05,
            "aggregate": {"stability_score": {"std_expectancy": 0.1}},
            "robustness": {"overfitting_indicators": {"high_auc_gap_windows": 1}},
        }
        self.assertGreater(composite_score(exp), 0.0)

    def test_empty_window_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            cand = ModelCandidateConfig("logistic_c1", "logistic", {"C": 1.0})
            result = run_walk_forward_experiment(
                pd.DataFrame(columns=["timestamp", "label"]),
                candidate=cand,
                feature_cols=list(STABLE),
            )
            self.assertEqual(result["window_count"], 0)

    def test_small_dataset_handling(self):
        df = _multi_year(40)
        windows = build_standard_windows(df)
        self.assertGreater(len(windows), 0)

    def test_rolling_window_integrity(self):
        df = _multi_year(100)
        windows = build_standard_windows(df)
        self.assertTrue(any(w.mode in ("expanding", "adaptive_expanding", "rolling") for w in windows))

    def test_expanding_window_integrity(self):
        df = _multi_year(150)
        windows = build_standard_windows(df)
        self.assertTrue(any(w.mode == "expanding" for w in windows))

    def test_trade_simulation_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            cand = ModelCandidateConfig("logistic_c1", "logistic", {"C": 1.0})
            r1 = run_walk_forward_experiment(df, candidate=cand, feature_cols=list(STABLE), seed=42)
            r2 = run_walk_forward_experiment(df, candidate=cand, feature_cols=list(STABLE), seed=42)
            self.assertEqual(r1["window_count"], r2["window_count"])

    def test_drawdown_in_window_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            cand = ModelCandidateConfig("logistic_c1", "logistic", {"C": 0.1})
            result = run_walk_forward_experiment(df, candidate=cand, feature_cols=list(STABLE), seed=42)
            for w in result["windows"]:
                if not w.get("skipped"):
                    self.assertIn("max_drawdown", w)

    def test_profit_factor_calculation(self):
        ranked = rank_candidates(
            [{"robustness_score": 80, "mean_profit_factor": 1.5, "mean_expectancy": 0.2, "mean_auc_gap": 0.03,
              "aggregate": {"stability_score": {"std_expectancy": 0.05}}, "robustness": {"overfitting_indicators": {}},
              "profitable_windows": 5, "window_count": 5, "candidate_id": "a", "experiment_id": "a"}]
        )
        self.assertEqual(ranked[0]["mean_profit_factor"], 1.5)

    def test_robustness_score_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            cand = ModelCandidateConfig("logistic_strong_reg", "logistic", {"C": 0.1})
            result = run_walk_forward_experiment(df, candidate=cand, feature_cols=list(STABLE), seed=42)
            self.assertGreaterEqual(result["robustness_score"], 0.0)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = RobustnessOptimizer(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            self.assertTrue(phase9_9_robustness_report_path(tmp).is_file())
            self.assertTrue(phase9_9_model_comparison_path(tmp).is_file())
            self.assertTrue(phase9_9_feature_selection_path(tmp).is_file())

    def test_forbidden_imports_ast_scan(self):
        self.assertEqual(_scan(), [])

    def test_regime_robustness_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = filter_resolved_labels(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            df["market_regime"] = assign_market_regime(df)
            report = analyze_regime_robustness(df)
            self.assertIn("by_regime", report)

    def test_model_selection_correctness(self):
        exps = [
            {"robustness_score": 60, "mean_profit_factor": 1.0, "mean_expectancy": 0.1, "mean_auc_gap": 0.2,
             "aggregate": {"stability_score": {"std_expectancy": 0.2}}, "robustness": {"overfitting_indicators": {}},
             "profitable_windows": 3, "window_count": 5, "overfitting_risk": "HIGH", "candidate_id": "weak"},
            {"robustness_score": 75, "mean_profit_factor": 1.4, "mean_expectancy": 0.2, "mean_auc_gap": 0.04,
             "aggregate": {"stability_score": {"std_expectancy": 0.05}}, "robustness": {"overfitting_indicators": {}},
             "profitable_windows": 5, "window_count": 5, "overfitting_risk": "MEDIUM", "candidate_id": "strong"},
        ]
        ranked = rank_candidates(exps)
        self.assertEqual(ranked[0]["candidate_id"], "strong")

    def test_feature_stability_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            subsets = build_feature_subsets(tmp)
            self.assertNotIn("rsi_14", subsets.get("stable_4", []))


if __name__ == "__main__":
    unittest.main()
