"""Phase 7.4 improvement recommendation tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.improvement.analyzer import ImprovementAnalyzer
from tradingbot.ml.improvement.experiment_queue import ExperimentQueue
from tradingbot.ml.improvement.feature_optimizer import FeatureOptimizer
from tradingbot.ml.improvement.model_optimizer import ModelOptimizer
from tradingbot.ml.improvement.recommendation import (
    experiment_queue_path,
    feature_improvement_path,
    improvement_recommendations_path,
)
from tradingbot.ml.improvement.regime_optimizer import RegimeOptimizer
from tradingbot.ml.improvement.reports import ImprovementReportGenerator
from tradingbot.ml.improvement.schema import ExperimentQueueItem, ImprovementOpportunity
from tradingbot.ml.improvement.threshold_optimizer import ThresholdRecommendationEngine

IMPROVE_PKG = ROOT / "tradingbot" / "ml" / "improvement"
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


def _write_reports(tmp: str) -> None:
    from tradingbot.ml.data.paths import reports_dir

    rep = reports_dir(tmp)
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "feature_research_report.json").write_text(
        json.dumps(
            {
                "importance": {"liquidity_sweep": 0.4, "spread_zscore": 0.02},
                "stability_scores": {"liquidity_sweep": 0.8, "spread_zscore": 0.3},
                "drift_scores": {"spread_zscore": 0.25},
                "correlation_changes": {"spread_zscore": 0.35},
                "unstable_features": ["spread_zscore"],
                "best_features": ["liquidity_sweep", "h4_trend_bias"],
                "regime_dependency": {"trend": {"h4_trend_bias": 0.5}, "range": {"spread_zscore": 0.4}},
                "session_dependency": {"london": {"liquidity_sweep": 0.45}},
            }
        ),
        encoding="utf-8",
    )
    (rep / "model_comparison.json").write_text(
        json.dumps(
            {
                "rankings": [
                    {
                        "model_name": "xgboost",
                        "roc_auc": 0.72,
                        "pr_auc": 0.65,
                        "expected_R": 0.15,
                        "calibration_error": 0.14,
                        "stability_score": 0.45,
                        "overall_score": 0.68,
                    }
                ],
                "best_model": "xgboost",
            }
        ),
        encoding="utf-8",
    )
    (rep / "paper_trading_report.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "win_rate": 0.45,
                    "max_drawdown_r": 22.0,
                    "expectancy_r": -0.1,
                    "trade_frequency": 80,
                },
                "session_breakdown": {"asia": {"expected_R": -0.2}},
            }
        ),
        encoding="utf-8",
    )
    (rep / "monitoring_summary.json").write_text(
        json.dumps({"feature_drift_score": 0.22, "degradation": {"status": "DEGRADED"}}),
        encoding="utf-8",
    )
    (rep / "experiment_report.json").write_text(
        json.dumps({"experiments": [{"model_name": "xgboost", "parameters": {"threshold": 0.5}}]}),
        encoding="utf-8",
    )
    (rep / "shadow_optimization.json").write_text(json.dumps({"best_threshold": 0.55}), encoding="utf-8")


class TestIsolation(unittest.TestCase):
    def test_no_execution_imports(self):
        self.assertEqual(_scan_package(IMPROVE_PKG), [])

    def test_no_kernel_imports(self):
        for path in IMPROVE_PKG.rglob("*.py"):
            self.assertNotIn("tradingbot.kernel", path.read_text(encoding="utf-8"))

    def test_no_risk_imports(self):
        for path in IMPROVE_PKG.rglob("*.py"):
            self.assertNotIn("tradingbot.adapters.risk_gate", path.read_text(encoding="utf-8"))


class TestAnalyzer(unittest.TestCase):
    def test_recommendation_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            opps = ImprovementAnalyzer(base_dir=tmp).analyze("XAUUSD", "M5")
            self.assertGreater(len(opps), 0)
            self.assertTrue(any("drawdown" in o.issue.lower() or "volatility" in o.issue.lower() for o in opps))


class TestFeatureOptimizer(unittest.TestCase):
    def test_feature_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            report = FeatureOptimizer(base_dir=tmp).write_report("XAUUSD", "M5")
            actions = {s["action"] for s in report["suggestions"]}
            self.assertTrue(actions & {"ADD", "REMOVE", "MODIFY"})
            self.assertTrue(feature_improvement_path(tmp).is_file())


class TestModelOptimizer(unittest.TestCase):
    def test_model_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            suggestions = ModelOptimizer(base_dir=tmp).analyze("XAUUSD", "M5")
            self.assertGreater(len(suggestions), 0)
            types = {s.suggestion_type for s in suggestions}
            self.assertTrue(types)


class TestThresholdOptimizer(unittest.TestCase):
    def test_threshold_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            suggestion = ThresholdRecommendationEngine(base_dir=tmp).analyze("XAUUSD", "M5")
            self.assertGreater(suggestion.recommended_threshold, suggestion.current_threshold)
            self.assertGreater(suggestion.confidence, 0.5)


class TestRegimeOptimizer(unittest.TestCase):
    def test_regime_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            suggestions = RegimeOptimizer(base_dir=tmp).analyze("XAUUSD", "M5")
            self.assertGreater(len(suggestions), 0)


class TestExperimentQueue(unittest.TestCase):
    def test_queue_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = ExperimentQueue(base_dir=tmp)
            item = queue.add(
                ExperimentQueueItem(
                    id="",
                    hypothesis="test hypothesis",
                    expected_improvement="+0.1R",
                    priority=80,
                    required_resources=["dataset"],
                )
            )
            self.assertTrue(experiment_queue_path(tmp).is_file())
            self.assertEqual(len(queue.list_all()), 1)
            self.assertEqual(item.status, "PENDING")


class TestReproducibility(unittest.TestCase):
    def test_reproducibility_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            report = ImprovementReportGenerator(base_dir=tmp).run("XAUUSD", "M5")
            self.assertIn("reproducibility", report)
            self.assertFalse(report["reproducibility"]["random_shuffle"])
            self.assertFalse(report["auto_apply"])

    def test_no_random_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            report = ImprovementReportGenerator(base_dir=tmp).run("XAUUSD", "M5")
            self.assertFalse(report["reproducibility"]["random_shuffle"])
            self.assertEqual(report["reproducibility"]["validation_method"], "chronological_split")


class TestReports(unittest.TestCase):
    def test_full_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_reports(tmp)
            report = ImprovementReportGenerator(base_dir=tmp).run("XAUUSD", "M5")
            self.assertTrue(improvement_recommendations_path(tmp).is_file())
            self.assertIn("top_improvements", report)
            self.assertFalse(report["live_enabled"])


if __name__ == "__main__":
    unittest.main()
