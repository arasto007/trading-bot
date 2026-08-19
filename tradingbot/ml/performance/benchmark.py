"""Benchmark runner — dataset sizes and operation timings."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.orchestrator.decision_engine import FinalDecisionEngine
from tradingbot.ml.orchestrator.schema import OrchestratorSnapshot
from tradingbot.ml.performance.memory import MemoryProfiler
from tradingbot.ml.performance.profiler import _synthetic_features
from tradingbot.ml.performance.schema import BenchmarkResult, utc_now_iso


DATASET_SIZES: tuple[int, ...] = (1000, 10000, 100000)


@dataclass
class BenchmarkRunner:
    """Benchmark feature, dataset, prediction, decision, and report operations."""

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    base_dir: str | Path | None = None
    sizes: tuple[int, ...] = DATASET_SIZES
    memory: MemoryProfiler | None = None
    results: list[BenchmarkResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.memory = self.memory or MemoryProfiler()

    def run_all(self) -> list[BenchmarkResult]:
        self.results = []
        for size in self.sizes:
            self.results.extend(self.run_for_size(size))
        return self.results

    def run_for_size(self, size: int) -> list[BenchmarkResult]:
        return [
            self.benchmark_feature_generation(size),
            self.benchmark_dataset_loading(size),
            self.benchmark_prediction_batch(size),
            self.benchmark_decision_generation(size),
            self.benchmark_report_generation(size),
        ]

    def _run(self, operation: str, size: int, func) -> BenchmarkResult:
        start = time.perf_counter()
        try:
            _, mem = self.memory.measure(func) if self.memory else (func(), None)
            elapsed = (time.perf_counter() - start) * 1000.0
            return BenchmarkResult(
                operation=operation,
                dataset_size=size,
                latency_ms=round(elapsed, 4),
                memory_mb=round(mem.peak_mb, 4) if mem else 0.0,
                success=True,
            )
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000.0
            return BenchmarkResult(operation, size, round(elapsed, 4), 0.0, success=False)

    def benchmark_feature_generation(self, size: int) -> BenchmarkResult:
        def _op() -> pd.DataFrame:
            df = _synthetic_features(size)
            df["feature_a"] = df["close"].rolling(10, min_periods=1).mean()
            df["feature_b"] = df["close"].rolling(20, min_periods=1).std().fillna(0.0)
            return df

        return self._run("feature_generation", size, _op)

    def benchmark_dataset_loading(self, size: int) -> BenchmarkResult:
        store = DatasetStore(self.base_dir)

        def _op() -> pd.DataFrame:
            df = _synthetic_features(size)
            store.store(self.symbol, self.timeframe, df)
            loaded = store.load(self.symbol, self.timeframe)
            assert loaded is not None
            return loaded

        return self._run("dataset_loading", size, _op)

    def benchmark_prediction_batch(self, size: int) -> BenchmarkResult:
        batch = min(size, 512)

        def _op() -> np.ndarray:
            x = np.random.default_rng(42).random((batch, 24))
            w = np.random.default_rng(1).random(24)
            return np.tanh(x @ w)

        return self._run("prediction_batch", size, _op)

    def benchmark_decision_generation(self, size: int) -> BenchmarkResult:
        engine = FinalDecisionEngine()
        count = min(max(size // 1000, 1), 50)

        def _op() -> int:
            total = 0
            for i in range(count):
                snap = OrchestratorSnapshot(
                    timestamp=utc_now_iso(),
                    symbol=self.symbol,
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
                total += 1
            return total

        return self._run("decision_generation", size, _op)

    def benchmark_report_generation(self, size: int) -> BenchmarkResult:
        def _op() -> str:
            payload = {
                "symbol": self.symbol,
                "rows": size,
                "metrics": {"latency_ms": 1.0},
                "generated_at": utc_now_iso(),
            }
            return json.dumps(payload, indent=2)

        return self._run("report_generation", size, _op)
