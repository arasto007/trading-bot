"""Performance optimization and latency profiling — Phase 7.2."""

from __future__ import annotations

from tradingbot.ml.performance.benchmark import BenchmarkRunner, DATASET_SIZES
from tradingbot.ml.performance.memory import MemoryProfiler
from tradingbot.ml.performance.optimization import OptimizationAdvisor
from tradingbot.ml.performance.profiler import MLPerformanceProfiler
from tradingbot.ml.performance.report import PerformanceReportGenerator, performance_profile_path
from tradingbot.ml.performance.schema import BenchmarkResult, PerformanceMetric, PerformanceProfile
from tradingbot.ml.performance.stress_latency import LatencyStressTester

__all__ = [
    "BenchmarkResult",
    "BenchmarkRunner",
    "DATASET_SIZES",
    "LatencyStressTester",
    "MLPerformanceProfiler",
    "MemoryProfiler",
    "OptimizationAdvisor",
    "PerformanceMetric",
    "PerformanceProfile",
    "PerformanceReportGenerator",
    "performance_profile_path",
]
