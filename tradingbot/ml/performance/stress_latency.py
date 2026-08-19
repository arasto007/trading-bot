"""Latency stress testing for repeated shadow workloads."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tradingbot.ml.infrastructure.health.health_checker import HealthChecker
from tradingbot.ml.orchestrator.decision_engine import FinalDecisionEngine
from tradingbot.ml.orchestrator.schema import OrchestratorSnapshot
from tradingbot.ml.performance.profiler import _synthetic_features
from tradingbot.ml.performance.schema import utc_now_iso


@dataclass
class LatencyStressResult:
    test_name: str
    iterations: int
    avg_ms: float
    p95_ms: float
    max_ms: float
    success: bool = True

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "iterations": self.iterations,
            "avg_ms": round(self.avg_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "success": self.success,
        }


@dataclass
class LatencyStressTester:
    """Stress latency under repeated predictions, batches, symbols, monitoring."""

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    base_dir: str | Path | None = None
    results: list[LatencyStressResult] = field(default_factory=list)

    def run_all(self) -> list[LatencyStressResult]:
        self.results = [
            self.test_repeated_predictions(iterations=100),
            self.test_large_feature_batches(rows=10000),
            self.test_multiple_symbols(["XAUUSD", "EURUSD", "GBPUSD"]),
            self.test_monitoring_load(iterations=20),
        ]
        return self.results

    @staticmethod
    def _summarize(test_name: str, timings: list[float]) -> LatencyStressResult:
        if not timings:
            return LatencyStressResult(test_name, 0, 0.0, 0.0, 0.0, success=False)
        ordered = sorted(timings)
        p95_idx = max(0, int(len(ordered) * 0.95) - 1)
        return LatencyStressResult(
            test_name=test_name,
            iterations=len(timings),
            avg_ms=statistics.mean(timings),
            p95_ms=ordered[p95_idx],
            max_ms=max(timings),
        )

    def test_repeated_predictions(self, iterations: int = 100) -> LatencyStressResult:
        timings: list[float] = []
        rng = np.random.default_rng(99)
        weights = rng.random(24)
        for _ in range(iterations):
            start = time.perf_counter()
            x = rng.random((1, 24))
            _ = 1 / (1 + np.exp(-(x @ weights)))
            timings.append((time.perf_counter() - start) * 1000.0)
        return self._summarize("repeated_predictions", timings)

    def test_large_feature_batches(self, rows: int = 10000) -> LatencyStressResult:
        timings: list[float] = []
        for _ in range(5):
            start = time.perf_counter()
            df = _synthetic_features(rows)
            df["roll_mean"] = df["close"].rolling(20, min_periods=1).mean()
            df["roll_std"] = df["close"].rolling(20, min_periods=1).std().fillna(0.0)
            timings.append((time.perf_counter() - start) * 1000.0)
        return self._summarize("large_feature_batches", timings)

    def test_multiple_symbols(self, symbols: list[str]) -> LatencyStressResult:
        engine = FinalDecisionEngine()
        timings: list[float] = []
        for symbol in symbols:
            start = time.perf_counter()
            snap = OrchestratorSnapshot(
                timestamp=utc_now_iso(),
                symbol=symbol,
                timeframe=self.timeframe,
                rule_signal="BUY",
                ml_prediction=1,
                ml_probability=0.7,
                hybrid_decision="BUY",
                hybrid_score=0.7,
                final_score=0.7,
                direction=1,
            )
            engine.generate_final_decision(snap)
            timings.append((time.perf_counter() - start) * 1000.0)
        return self._summarize("multiple_symbols", timings)

    def test_monitoring_load(self, iterations: int = 20) -> LatencyStressResult:
        checker = HealthChecker(self.base_dir)
        timings: list[float] = []
        for _ in range(iterations):
            start = time.perf_counter()
            checker.check_all(self.symbol, self.timeframe)
            timings.append((time.perf_counter() - start) * 1000.0)
        return self._summarize("monitoring_load", timings)
