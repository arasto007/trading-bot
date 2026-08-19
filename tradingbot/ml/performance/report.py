"""Performance report generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.performance.benchmark import BenchmarkRunner
from tradingbot.ml.performance.optimization import OptimizationAdvisor
from tradingbot.ml.performance.profiler import MLPerformanceProfiler
from tradingbot.ml.performance.schema import PerformanceProfile
from tradingbot.ml.performance.stress_latency import LatencyStressTester


def performance_profile_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "performance_profile.json"


@dataclass
class PerformanceReportGenerator:
    """Run profiler, benchmarks, stress tests, and write performance_profile.json."""

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    base_dir: str | Path | None = None
    feature_rows: int = 1000

    def generate(self) -> dict[str, Any]:
        profiler = MLPerformanceProfiler(self.symbol, self.timeframe, self.base_dir)
        metrics = profiler.profile_all(feature_rows=self.feature_rows)

        benchmark = BenchmarkRunner(self.symbol, self.timeframe, self.base_dir)
        bench_results = benchmark.run_all()

        stress = LatencyStressTester(self.symbol, self.timeframe, self.base_dir)
        stress_results = stress.run_all()

        advisor = OptimizationAdvisor()
        recommendations = advisor.to_dict_list(advisor.analyze(metrics, bench_results))

        by_component = {m.component: m for m in metrics}

        def _ms(name: str) -> float:
            return by_component[name].latency_ms if name in by_component else 0.0

        profile = PerformanceProfile(
            system="OK",
            average_prediction_ms=_ms("model_prediction_time"),
            feature_build_ms=_ms("feature_build_time"),
            orchestrator_ms=_ms("orchestrator_time"),
            hybrid_decision_ms=_ms("hybrid_decision_time"),
            monitoring_ms=_ms("monitoring_time"),
            logging_ms=_ms("logging_time"),
            memory_usage_mb=max([m.memory_mb for m in metrics] + [b.memory_mb for b in bench_results], default=0.0),
            metrics=metrics,
            benchmarks=bench_results,
            recommendations=recommendations,
        )

        payload = profile.to_dict()
        payload["stress_latency"] = [r.to_dict() for r in stress_results]
        payload["symbol"] = self.symbol
        payload["timeframe"] = self.timeframe

        path = performance_profile_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload
