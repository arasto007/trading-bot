"""ML performance profiler — latency measurement for shadow pipeline."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from tradingbot.ml.infrastructure.health.health_checker import HealthChecker
from tradingbot.ml.orchestrator.decision_engine import FinalDecisionEngine
from tradingbot.ml.orchestrator.schema import OrchestratorSnapshot
from tradingbot.ml.performance.memory import MemoryProfiler
from tradingbot.ml.performance.schema import PerformanceMetric, utc_now_iso


def _synthetic_features(n: int = 500) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
            "open": 2000 + rng.random(n),
            "high": 2001 + rng.random(n),
            "low": 1999 + rng.random(n),
            "close": 2000 + rng.random(n),
            "volume": rng.integers(100, 1000, size=n),
        }
    )


@dataclass
class MLPerformanceProfiler:
    """Measure latency and memory for shadow ML components."""

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    base_dir: str | Path | None = None
    memory: MemoryProfiler | None = None
    metrics: list[PerformanceMetric] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.memory = self.memory or MemoryProfiler()

    def profile_all(self, *, feature_rows: int = 1000) -> list[PerformanceMetric]:
        self.metrics = [
            self.profile_feature_build(feature_rows),
            self.profile_model_prediction(feature_rows),
            self.profile_hybrid_decision(),
            self.profile_orchestrator(),
            self.profile_monitoring(),
            self.profile_logging(),
        ]
        return self.metrics

    def _timed(self, component: str, func: Callable[[], Any]) -> PerformanceMetric:
        assert self.memory is not None
        start = time.perf_counter()
        _, mem = self.memory.measure(func)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return PerformanceMetric(
            component=component,
            latency_ms=round(elapsed_ms, 4),
            memory_mb=round(mem.peak_mb, 4),
            timestamp=utc_now_iso(),
        )

    def profile_feature_build(self, rows: int = 1000) -> PerformanceMetric:
        def _build() -> pd.DataFrame:
            df = _synthetic_features(rows)
            out = df.copy()
            out["returns"] = out["close"].pct_change().fillna(0.0)
            out["sma_20"] = out["close"].rolling(20, min_periods=1).mean()
            out["volatility"] = out["returns"].rolling(14, min_periods=1).std().fillna(0.0)
            out["atr"] = (out["high"] - out["low"]).rolling(14, min_periods=1).mean()
            return out

        return self._timed("feature_build_time", _build)

    def profile_model_prediction(self, rows: int = 1000) -> PerformanceMetric:
        def _predict() -> np.ndarray:
            features = np.random.default_rng(42).random((min(rows, 256), 32))
            weights = np.random.default_rng(7).random(32)
            logits = features @ weights
            return 1 / (1 + np.exp(-logits))

        return self._timed("model_prediction_time", _predict)

    def profile_hybrid_decision(self) -> PerformanceMetric:
        from tradingbot.ml.hybrid.config import HybridConfig
        from tradingbot.ml.hybrid.schema import MLSignal, RuleSignal
        from tradingbot.ml.hybrid.scoring import compute_final_score

        rule = RuleSignal(direction=1, strength=0.65)
        ml = MLSignal(prediction=1, probability=0.72, direction="BUY", confidence="HIGH", accepted=True)
        config = HybridConfig()

        def _hybrid() -> float:
            return compute_final_score(rule, ml, config=config, resolved_direction=1)

        return self._timed("hybrid_decision_time", _hybrid)

    def profile_orchestrator(self) -> PerformanceMetric:
        snapshot = OrchestratorSnapshot(
            timestamp=utc_now_iso(),
            symbol=self.symbol,
            timeframe=self.timeframe,
            rule_signal="BUY",
            ml_prediction=1,
            ml_probability=0.72,
            hybrid_decision="BUY",
            hybrid_score=0.75,
            final_score=0.75,
            direction=1,
            regime="trend",
            ab_winner="HYBRID_BETTER",
            performance_state="HEALTHY",
        )

        def _orchestrate():
            return FinalDecisionEngine().generate_final_decision(snapshot)

        return self._timed("orchestrator_time", _orchestrate)

    def profile_monitoring(self) -> PerformanceMetric:
        def _monitor() -> Any:
            return HealthChecker(self.base_dir).check_all(self.symbol, self.timeframe)

        return self._timed("monitoring_time", _monitor)

    def profile_logging(self) -> PerformanceMetric:
        def _log() -> str:
            payload = {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "action": "WAIT",
                "trace": {"benchmark": True},
            }
            return json.dumps(payload)

        return self._timed("logging_time", _log)
