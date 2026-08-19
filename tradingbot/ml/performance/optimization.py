"""Optimization advisor — bottleneck analysis and recommendations."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.performance.schema import BenchmarkResult, PerformanceMetric


@dataclass
class OptimizationRecommendation:
    bottleneck: str
    latency_ms: float
    recommendation: str
    severity: str = "medium"

    def to_dict(self) -> dict:
        return {
            "bottleneck": self.bottleneck,
            "latency_ms": round(self.latency_ms, 2),
            "recommendation": self.recommendation,
            "severity": self.severity,
        }


@dataclass
class OptimizationAdvisor:
    """Analyze profiler/benchmark output and suggest optimizations."""

    feature_build_threshold_ms: float = 200.0
    prediction_threshold_ms: float = 50.0
    orchestrator_threshold_ms: float = 30.0
    monitoring_threshold_ms: float = 100.0
    dataset_load_threshold_ms: float = 500.0

    def analyze(
        self,
        metrics: list[PerformanceMetric],
        benchmarks: list[BenchmarkResult] | None = None,
    ) -> list[OptimizationRecommendation]:
        recs: list[OptimizationRecommendation] = []
        for metric in metrics:
            rec = self._from_metric(metric)
            if rec:
                recs.append(rec)

        benchmarks = benchmarks or []
        for bench in benchmarks:
            rec = self._from_benchmark(bench)
            if rec:
                recs.append(rec)

        if not recs:
            return []
        return sorted(recs, key=lambda r: r.latency_ms, reverse=True)

    def _from_metric(self, metric: PerformanceMetric) -> OptimizationRecommendation | None:
        mapping = {
            "feature_build_time": (
                self.feature_build_threshold_ms,
                "cache HTF alignment and precompute rolling features",
            ),
            "model_prediction_time": (
                self.prediction_threshold_ms,
                "batch predictions and cache scaler transforms",
            ),
            "hybrid_decision_time": (
                self.orchestrator_threshold_ms,
                "memoize rule+ML agreement checks per bar",
            ),
            "orchestrator_time": (
                self.orchestrator_threshold_ms,
                "reduce ensemble weight recalculation per tick",
            ),
            "monitoring_time": (
                self.monitoring_threshold_ms,
                "cache monitoring snapshots with incremental updates",
            ),
            "logging_time": (
                20.0,
                "use buffered JSONL append with async flush",
            ),
        }
        if metric.component not in mapping:
            return None
        threshold, recommendation = mapping[metric.component]
        if metric.latency_ms <= threshold:
            return None
        severity = "high" if metric.latency_ms > threshold * 2 else "medium"
        return OptimizationRecommendation(
            bottleneck=metric.component,
            latency_ms=metric.latency_ms,
            recommendation=recommendation,
            severity=severity,
        )

    def _from_benchmark(self, bench: BenchmarkResult) -> OptimizationRecommendation | None:
        if bench.operation == "dataset_loading" and bench.latency_ms > self.dataset_load_threshold_ms:
            return OptimizationRecommendation(
                bottleneck="dataset_loader",
                latency_ms=bench.latency_ms,
                recommendation="partition parquet by month and use column pruning",
                severity="high" if bench.dataset_size >= 100000 else "medium",
            )
        if bench.operation == "feature_generation" and bench.latency_ms > self.feature_build_threshold_ms:
            return OptimizationRecommendation(
                bottleneck="feature_builder",
                latency_ms=bench.latency_ms,
                recommendation="cache HTF alignment and vectorize rolling windows",
                severity="high" if bench.dataset_size >= 100000 else "medium",
            )
        return None

    def to_dict_list(self, recommendations: list[OptimizationRecommendation]) -> list[dict]:
        return [r.to_dict() for r in recommendations]
