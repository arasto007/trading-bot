"""Phase 9.3 ML research optimization tests (offline only)."""

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
    feature_importance_report_path,
    label_experiments_report_path,
    model_optimization_report_path,
    phase9_3_research_report_path,
    sampling_analysis_report_path,
    threshold_analysis_report_path,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.deep_audit import deep_audit_report_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.feature_importance_analysis import run_feature_importance_analysis
from tradingbot.ml.research.label_experiment import run_label_experiments
from tradingbot.ml.research.model_optimizer import run_model_optimization
from tradingbot.ml.research.research_orchestrator import MLResearchOptimizer
from tradingbot.ml.research.research_utils import dataset_content_fingerprint, load_research_context
from tradingbot.ml.research.sampling_analysis import run_sampling_analysis
from tradingbot.ml.research.threshold_optimizer import run_threshold_optimization
from tradingbot.ml.training.data_loader import assert_no_test_leakage, load_dataset_v2_splits
from tradingbot.ml.training.phase9_production import Phase92ProductionTrainer

try:
    import lightgbm  # noqa: F401
    import xgboost  # noqa: F401

    HAS_BOOSTERS = True
except ImportError:
    HAS_BOOSTERS = False

RESEARCH_PKG = ROOT / "tradingbot" / "ml" / "research"
PHASE93_FILES = (
    "feature_importance_analysis.py",
    "label_experiment.py",
    "sampling_analysis.py",
    "model_optimizer.py",
    "threshold_optimizer.py",
    "research_orchestrator.py",
    "research_utils.py",
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
        ["bos", "choch", "liquidity_sweep", "fvg", "order_block", "session_transition"],
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


def _write_passing_deep_audit(tmp: str) -> None:
    path = deep_audit_report_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "pass", "phase": "9.1.5", "health_score": 97.5}), encoding="utf-8")


def _setup_research_env(tmp: str, *, n: int = 1100, seed: int = 42) -> str:
    source = _synthetic_source(n, seed=seed)
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", source)
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    _write_candles(tmp, n=n + 100)
    _write_passing_deep_audit(tmp)
    Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run("XAUUSD", "M5")
    return dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))


@unittest.skipUnless(HAS_BOOSTERS, "xgboost and lightgbm required")
class TestPhase93Research(unittest.TestCase):
    def test_feature_importance_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            ctx = load_research_context("XAUUSD", "M5", tmp, seed=42)
            report = run_feature_importance_analysis(ctx, seed=42)
            self.assertIn("rankings", report)
            self.assertGreater(len(report["rankings"]), 0)
            self.assertIn("model_agreement", report)
            self.assertIn("detection", report)
            top = report["rankings"][0]
            self.assertIn("feature", top)
            self.assertIn("importance_score", top)
            self.assertIn("rank", top)
            self.assertIn("model_agreement_score", top)

    def test_no_dataset_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp_before = _setup_research_env(tmp)
            store = DatasetStore(tmp)
            labels_before = store.load_v2("XAUUSD", "M5")["label"].copy()
            run_label_experiments("XAUUSD", "M5", tmp)
            fp_after = dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))
            labels_after = store.load_v2("XAUUSD", "M5")["label"]
            self.assertEqual(fp_before, fp_after)
            pd.testing.assert_series_equal(labels_before, labels_after)

    def test_label_experiment_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            report = run_label_experiments("XAUUSD", "M5", tmp)
            self.assertIn("experiments", report)
            self.assertEqual(len(report["experiments"]), 27)
            exp = report["experiments"][0]
            for key in (
                "tp_percentage",
                "sl_percentage",
                "unresolved_percentage",
                "class_balance_tp_rate",
                "atr_period",
                "tp_r_multiple",
                "future_window_bars",
            ):
                self.assertIn(key, exp)

    def test_no_leakage_in_research_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            ctx = load_research_context("XAUUSD", "M5", tmp)
            assert_no_test_leakage(ctx.splits)

    def test_chronological_validation_in_optimizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            ctx = load_research_context("XAUUSD", "M5", tmp, seed=42)
            report = run_model_optimization(ctx, seed=42)
            rules = report["validation_rules"]
            self.assertTrue(rules["chronological_split"])
            self.assertFalse(rules["shuffle"])
            self.assertFalse(rules["test_used_in_optimization"])

    def test_threshold_optimization_correctness(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            ctx = load_research_context("XAUUSD", "M5", tmp)
            report = run_threshold_optimization(ctx)
            val_rows = report["by_split"]["validation"]
            self.assertEqual(len(val_rows), 5)
            for row in val_rows:
                self.assertIn("precision", row)
                self.assertIn("recall", row)
                self.assertIn("win_rate_proxy", row)
                self.assertIn("trade_frequency", row)
            self.assertIn("best_threshold_validation", report)

    def test_optimizer_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp, seed=99)
            ctx = load_research_context("XAUUSD", "M5", tmp, seed=42)
            r1 = run_model_optimization(ctx, seed=42)
            r2 = run_model_optimization(ctx, seed=42)
            self.assertEqual(r1["models"][0]["best_params"], r2["models"][0]["best_params"])
            self.assertEqual(r1["models"][1]["best_params"], r2["models"][1]["best_params"])

    def test_sampling_analysis_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            ctx = load_research_context("XAUUSD", "M5", tmp)
            report = run_sampling_analysis(ctx)
            self.assertIn("by_event_type", report)
            self.assertGreater(report["total_samples"], 0)
            for entry in report["by_event_type"]:
                self.assertIn("win_rate", entry)
                self.assertIn("sample_count", entry)

    def test_full_orchestrator_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            result = MLResearchOptimizer(base_dir=tmp, seed=42, skip_slow=True).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            self.assertEqual(result.status, "PASS")
            self.assertTrue(phase9_3_research_report_path(tmp).is_file())
            payload = json.loads(phase9_3_research_report_path(tmp).read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertIn("best_model", payload)
            self.assertIn("best_features", payload)
            self.assertIn("best_threshold", payload)
            self.assertIn("best_label_configuration", payload)
            self.assertIn("recommendations", payload)
            self.assertTrue(feature_importance_report_path(tmp).is_file())
            self.assertTrue(label_experiments_report_path(tmp).is_file())
            self.assertTrue(sampling_analysis_report_path(tmp).is_file())
            self.assertTrue(threshold_analysis_report_path(tmp).is_file())

    def test_orchestrator_all_reports_when_not_skipping_slow(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp, n=1100)
            result = MLResearchOptimizer(base_dir=tmp, seed=42, skip_slow=False).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            self.assertTrue(model_optimization_report_path(tmp).is_file())

    def test_blocked_without_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = MLResearchOptimizer(base_dir=tmp).run("XAUUSD", "M5")
            self.assertTrue(result.blocked)

    def test_blocked_without_trained_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _synthetic_source(1100)
            DatasetStore(tmp).store("XAUUSD", "M5", source)
            ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
            result = MLResearchOptimizer(base_dir=tmp, skip_slow=True).run("XAUUSD", "M5")
            self.assertTrue(result.blocked)
            self.assertIn("not found", result.block_reason.lower())

    def test_load_splits_feature_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup_research_env(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            self.assertEqual(len(splits.feature_columns), len(feature_names()))

    def test_label_experiments_without_candles_baseline_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _synthetic_source(200)
            DatasetStore(tmp).store("XAUUSD", "M5", source)
            ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
            report = run_label_experiments("XAUUSD", "M5", tmp)
            self.assertEqual(report["experiments"], [])
            self.assertTrue(any("no candle" in n for n in report["notes"]))


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE93_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
