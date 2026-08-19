"""Phase 7.2 performance profiling tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.performance.benchmark import DATASET_SIZES, BenchmarkRunner
from tradingbot.ml.performance.memory import MemoryProfiler
from tradingbot.ml.performance.optimization import OptimizationAdvisor
from tradingbot.ml.performance.profiler import MLPerformanceProfiler
from tradingbot.ml.performance.report import PerformanceReportGenerator, performance_profile_path
from tradingbot.ml.performance.schema import PerformanceMetric
from tradingbot.ml.performance.stress_latency import LatencyStressTester

PERF_PKG = ROOT / "tradingbot" / "ml" / "performance"
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


class TestIsolation(unittest.TestCase):
    def test_no_execution_imports(self):
        self.assertEqual(_scan_package(PERF_PKG), [])


class TestProfiler(unittest.TestCase):
    def test_profiler_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = MLPerformanceProfiler(base_dir=tmp).profile_all(feature_rows=500)
            self.assertEqual(len(metrics), 6)
            names = {m.component for m in metrics}
            self.assertIn("feature_build_time", names)
            self.assertIn("model_prediction_time", names)
            for metric in metrics:
                self.assertGreaterEqual(metric.latency_ms, 0.0)
                self.assertGreaterEqual(metric.memory_mb, 0.0)

    def test_latency_measurement(self):
        profiler = MLPerformanceProfiler()
        metric = profiler.profile_logging()
        self.assertEqual(metric.component, "logging_time")
        self.assertGreater(metric.latency_ms, 0.0)


class TestBenchmark(unittest.TestCase):
    def test_benchmark_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = BenchmarkRunner(base_dir=tmp, sizes=(1000,)).run_all()
            r2 = BenchmarkRunner(base_dir=tmp, sizes=(1000,)).run_all()
            self.assertEqual(len(r1), len(r2))
            self.assertEqual({r.operation for r in r1}, {r.operation for r in r2})

    def test_large_dataset_handling(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = BenchmarkRunner(base_dir=tmp, sizes=(1000, 10000))
            results = runner.run_all()
            self.assertEqual(len(results), 10)
            for size in (1000, 10000):
                self.assertTrue(any(r.dataset_size == size for r in results))


class TestMemory(unittest.TestCase):
    def test_memory_tracking(self):
        profiler = MemoryProfiler()

        def _alloc() -> list[int]:
            return [i for i in range(100000)]

        _, snap = profiler.measure(_alloc)
        self.assertGreater(snap.peak_mb, 0.0)


class TestOptimization(unittest.TestCase):
    def test_optimization_advisor(self):
        metrics = [
            PerformanceMetric("feature_build_time", 420.0, 10.0),
            PerformanceMetric("logging_time", 1.0, 0.1),
        ]
        recs = OptimizationAdvisor().analyze(metrics)
        self.assertTrue(any(r.bottleneck == "feature_build_time" for r in recs))


class TestStressLatency(unittest.TestCase):
    def test_stress_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = LatencyStressTester(base_dir=tmp).run_all()
            self.assertEqual(len(results), 4)
            for result in results:
                self.assertTrue(result.success)


class TestReport(unittest.TestCase):
    def test_diagnostic_report_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = PerformanceReportGenerator(
                base_dir=tmp,
                feature_rows=500,
            ).generate()
            path = performance_profile_path(tmp)
            self.assertTrue(path.is_file())
            self.assertEqual(payload["system"], "OK")
            self.assertIn("average_prediction_ms", payload)
            self.assertIn("recommendations", payload)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["system"], "OK")


if __name__ == "__main__":
    unittest.main()
