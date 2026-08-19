"""Phase 7.3 ML research intelligence tests."""

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

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry import feature_names
from tradingbot.ml.research.experiment_runner import ExperimentConfig, ResearchExperimentRunner
from tradingbot.ml.research.experiment_tracker import ExperimentTracker
from tradingbot.ml.research.feature_research import FeatureResearchAnalyzer
from tradingbot.ml.research.hypothesis import HypothesisManager
from tradingbot.ml.research.model_comparison import ModelComparisonEngine
from tradingbot.ml.research.ranking import ResearchRanker
from tradingbot.ml.research.reproducibility import build_reproducibility_bundle, dataset_fingerprint, verify_reproducibility
from tradingbot.ml.research.reports import ResearchReportGenerator
from tradingbot.ml.research.schema import ExperimentRecord, utc_now_iso

RESEARCH_PKG = ROOT / "tradingbot" / "ml" / "research"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _scan_package(package_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in package_dir.rglob("*.py"):
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
                    if module.startswith(prefix):
                        violations.append(f"{path.relative_to(package_dir)}: {module}")
    return violations


def _make_dataset(n: int = 120, seed: int = 42) -> pd.DataFrame:
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
        "label": labels,
        "split": splits,
        "regime": rng.choice(["trend", "range"], n),
        "session": rng.choice(["london", "asia"], n),
    }
    for feat in feature_names()[:10]:
        row[feat] = rng.normal(0, 1, n)
    row["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.1, n)
    row["liquidity_sweep"] = rng.normal(0, 1, n)
    return pd.DataFrame(row)


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in RESEARCH_PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.kernel", text)

    def test_no_risk_imports(self):
        for path in RESEARCH_PKG.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.adapters.risk_gate", text)

    def test_no_execution_imports(self):
        violations = _scan_package(RESEARCH_PKG)
        self.assertEqual(violations, [])


class TestExperimentTracker(unittest.TestCase):
    def test_experiment_logging(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ExperimentTracker(tmp)
            record = ExperimentRecord(
                experiment_id="exp-1",
                timestamp=utc_now_iso(),
                dataset_hash="abc",
                feature_version="2.0",
                model_name="logistic",
                model_version="1.0",
                parameters={"threshold": 0.5},
                validation_method="chronological_split",
                metrics={"roc_auc": 0.7},
                expected_R=0.2,
            )
            tracker.append(record)
            rows = tracker.read_all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["experiment_id"], "exp-1")

    def test_append_only_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ExperimentTracker(tmp)
            tracker.append({"experiment_id": "a", "timestamp": utc_now_iso(), "dataset_hash": "x", "feature_version": "2.0", "model_name": "logistic", "model_version": "1.0", "parameters": {}, "validation_method": "walk_forward", "metrics": {}, "expected_R": 0.0})
            tracker.append({"experiment_id": "b", "timestamp": utc_now_iso(), "dataset_hash": "x", "feature_version": "2.0", "model_name": "xgboost", "model_version": "1.0", "parameters": {}, "validation_method": "walk_forward", "metrics": {}, "expected_R": 0.1})
            original = tracker.path.read_text(encoding="utf-8")
            tracker.append({"experiment_id": "c", "timestamp": utc_now_iso(), "dataset_hash": "x", "feature_version": "2.0", "model_name": "lightgbm", "model_version": "1.0", "parameters": {}, "validation_method": "walk_forward", "metrics": {}, "expected_R": 0.2})
            updated = tracker.path.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith(original))
            self.assertEqual(tracker.count(), 3)


class TestFeatureResearch(unittest.TestCase):
    def test_feature_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            report = FeatureResearchAnalyzer(tmp).analyze("XAUUSD", "M5")
            self.assertGreater(report["feature_count"], 0)
            self.assertIn("best_features", report)
            self.assertIn("regime_dependency", report)


class TestModelComparison(unittest.TestCase):
    def test_model_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tradingbot.ml.data.paths import reports_dir

            reports_dir(tmp).mkdir(parents=True, exist_ok=True)
            payload = {
                "metrics": {"roc_auc": 0.72, "pr_auc": 0.65, "stability_score": 0.8, "calibration_error": 0.08},
                "trading": {"expected_R": 0.25},
                "simulated": {"trades_taken": 100, "profit_factor": 1.4, "max_drawdown": 5.0},
            }
            (reports_dir(tmp) / "XAUUSD_M5_logistic_evaluation.json").write_text(json.dumps(payload), encoding="utf-8")
            result = ModelComparisonEngine(tmp).compare("XAUUSD", "M5")
            self.assertFalse(result["auto_replacement"])
            if result["rankings"]:
                self.assertIn("overall_score", result["rankings"][0])


class TestRanking(unittest.TestCase):
    def test_ranking_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ExperimentTracker(tmp)
            for i, er in enumerate((0.1, 0.3, 0.2)):
                tracker.append({
                    "experiment_id": f"e{i}",
                    "timestamp": utc_now_iso(),
                    "dataset_hash": "x",
                    "feature_version": "2.0",
                    "model_name": "logistic",
                    "model_version": "1.0",
                    "parameters": {},
                    "validation_method": "chronological_split",
                    "metrics": {"roc_auc": 0.5 + i * 0.1, "f1": 0.5},
                    "expected_R": er,
                })
            ranks = ResearchRanker(tmp).rank_all("XAUUSD", "M5")
            exp_ranks = ranks["experiments"]
            self.assertEqual(exp_ranks[0]["expected_R"], 0.3)


class TestReproducibility(unittest.TestCase):
    def test_reproducibility_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            bundle = build_reproducibility_bundle("XAUUSD", "M5", model_name="logistic", model_version="1.0", parameters={"threshold": 0.5}, base_dir=tmp)
            self.assertIn("dataset_fingerprint", bundle)
            self.assertIn("feature_schema", bundle)
            self.assertIn("git_commit", bundle)

    def test_no_random_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            runner = ResearchExperimentRunner("XAUUSD", "M5", base_dir=tmp)
            record = runner.run(ExperimentConfig(model_name="logistic", validation_method="chronological_split"))
            self.assertEqual(record.validation_method, "chronological_split")
            self.assertNotIn("shuffle", json.dumps(record.parameters))


class TestExperimentRunner(unittest.TestCase):
    def test_offline_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            runner = ResearchExperimentRunner("XAUUSD", "M5", base_dir=tmp)
            record = runner.run()
            self.assertEqual(runner.tracker.count(), 1)
            self.assertIn("roc_auc", record.metrics)


class TestReports(unittest.TestCase):
    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            payload = ResearchReportGenerator(base_dir=tmp).run("XAUUSD", "M5")
            self.assertIn("summary", payload)
            self.assertTrue(Path(payload["feature_research_report"]).is_file())


if __name__ == "__main__":
    unittest.main()
