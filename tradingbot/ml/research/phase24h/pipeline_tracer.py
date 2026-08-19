"""Phase 24H — runtime execution tracer for duplicate pipeline detection."""

from __future__ import annotations

import inspect
import time
import traceback
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

STAGE_IDS = (
    "DataStage",
    "IndicatorStage",
    "PipelineCache.get_unified_frame",
    "build_unified_frame",
    "build_ml_features",
    "FeatureBuilder.compute_at",
    "RangeEngineAdapter.evaluate",
    "TrendEngine.evaluate",
    "predict_proba",
    "build_market_context",
    "DecisionOrchestrator",
    "Calibration",
    "TradeQuality",
    "AdaptiveRisk",
    "ProfitabilityFilters",
    "HealthGate",
    "RiskGate",
    "ExecutionStage",
    "normalize_candles_for_builder",
    "rule_classify_row",
)


@dataclass
class ExecutionEvent:
    stage: str
    candle_id: str
    seq: int
    caller: str
    file: str
    line: int
    duration_ms: float
    purpose: str


@dataclass
class ExecutionTracer:
    candle_id: str = ""
    events: list[ExecutionEvent] = field(default_factory=list)
    timings: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _seq: int = 0
    _active: bool = False
    _originals: dict[str, Any] = field(default_factory=dict)

    def record(self, stage: str, duration_ms: float, *, purpose: str = "") -> None:
        if not self._active:
            return
        frame = inspect.stack()[2]
        self._seq += 1
        evt = ExecutionEvent(
            stage=stage,
            candle_id=self.candle_id,
            seq=self._seq,
            caller=f"{frame.filename.split('tradingbot')[-1].replace(chr(92), '/')}:{frame.function}",
            file=frame.filename,
            line=frame.lineno,
            duration_ms=duration_ms,
            purpose=purpose,
        )
        self.events.append(evt)
        self.timings[stage].append(duration_ms)

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STAGE_IDS}
        for evt in self.events:
            out[evt.stage] = out.get(evt.stage, 0) + 1
        return out

    def execution_order(self) -> list[dict[str, Any]]:
        return [
            {
                "seq": e.seq,
                "stage": e.stage,
                "caller": e.caller,
                "file": e.file.split("tradingbot")[-1].replace("\\", "/"),
                "line": e.line,
                "duration_ms": round(e.duration_ms, 4),
                "purpose": e.purpose,
            }
            for e in self.events
        ]

    def _wrap(self, stage: str, fn: Callable, *, purpose: str = "") -> Callable:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.record(stage, (time.perf_counter() - t0) * 1000, purpose=purpose)

        return wrapped

    @contextmanager
    def trace(self, candle_id: str) -> Iterator[ExecutionTracer]:
        self.candle_id = candle_id
        self.events.clear()
        self.timings.clear()
        self._seq = 0
        self._active = True

        import pandas as pd

        from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
        from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
        from tradingbot.ml.decision_engine import validation as val_mod
        from tradingbot.ml.features.builder import FeatureBuilder
        from tradingbot.ml.integration import health_gate as hg_mod
        from tradingbot.ml.integration import pipeline_cache as pc_mod
        from tradingbot.ml.integration.kernel_adapter import KernelAdapter
        from tradingbot.ml.phase19c import filters as filt_mod
        from tradingbot.ml.research.phase13_9 import unified_features as uf_mod
        from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
        from tradingbot.ml.research.regime_router import phase99_feature_validation as p99_mod
        from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
        from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
        from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine
        from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
        from tradingbot.pipeline.data_stage import DataStage
        from tradingbot.pipeline.indicator_stage import IndicatorStage

        patches: list[tuple[Any, str, Callable]] = []

        def _patch(module: Any, name: str, stage: str, purpose: str = "") -> None:
            orig = getattr(module, name)
            patches.append((module, name, orig))
            setattr(module, name, self._wrap(stage, orig, purpose=purpose))

        _patch(pc_mod.PipelineCache, "get_unified_frame", "PipelineCache.get_unified_frame", "unified feature matrix")
        _patch(uf_mod, "build_unified_frame", "build_unified_frame", "canonical ML features")

        import tradingbot.ml.research.trend_ml.feature_builder as fb_mod

        _patch(fb_mod, "build_ml_features", "build_ml_features", "trend feature matrix")
        _patch(FeatureBuilder, "compute_at", "FeatureBuilder.compute_at", "range live feature vector")
        _patch(RangeEngineAdapter, "evaluate", "RangeEngineAdapter.evaluate", "range engine inference")
        _patch(val_mod, "build_market_context", "build_market_context", "engine context assembly")
        _patch(DecisionOrchestrator, "decide", "DecisionOrchestrator", "engine routing decision")
        _patch(AdaptiveRiskEngine, "recommend", "AdaptiveRisk", "ML position sizing")
        _patch(TradeQualityEngine, "evaluate", "TradeQuality", "trade quality gate")
        _patch(filt_mod, "apply_profitability_filters", "ProfitabilityFilters", "RSI/ADX filters")
        _patch(hg_mod, "require_health", "HealthGate", "pre-decision validation")
        _patch(hg_mod, "run_pre_decision_health", "HealthGate", "health checks")
        _patch(p99_mod, "normalize_candles_for_builder", "normalize_candles_for_builder", "candle index normalize")
        from tradingbot.ml.research.regime_detector import regime_classifier as rc_mod

        _patch(rc_mod, "rule_classify_row", "rule_classify_row", "regime label per row")

        orig_data_run = DataStage.run
        orig_ind_run = IndicatorStage.run

        async def data_run_traced(self_ds, ctx, portfolio_snapshot):
            t0 = time.perf_counter()
            try:
                return await orig_data_run(self_ds, ctx, portfolio_snapshot)
            finally:
                ExecutionTracer.record(self, "DataStage", (time.perf_counter() - t0) * 1000, purpose="load OHLCV")

        async def ind_run_traced(self_is, ctx, portfolio_snapshot):
            t0 = time.perf_counter()
            try:
                return await orig_ind_run(self_is, ctx, portfolio_snapshot)
            finally:
                ExecutionTracer.record(self, "IndicatorStage", (time.perf_counter() - t0) * 1000, purpose="legacy indicators")

        DataStage.run = data_run_traced
        IndicatorStage.run = ind_run_traced

        trend_eval_holder: dict[str, Any] = {}

        def _patch_trend_eval(engine_cls: type, stage_name: str) -> None:
            if engine_cls is None:
                return
            orig_eval = engine_cls.evaluate

            def trend_eval_wrapped(self_eng, *args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return orig_eval(self_eng, *args, **kwargs)
                finally:
                    ExecutionTracer.record(self, stage_name, (time.perf_counter() - t0) * 1000, purpose="trend inference")

            engine_cls.evaluate = trend_eval_wrapped
            trend_eval_holder[stage_name] = (engine_cls, orig_eval)

        try:
            from tradingbot.ml.phase17d.v41_engine import TrendRfV41Engine

            _patch_trend_eval(TrendRfV41Engine, "TrendEngine.evaluate")
        except ImportError:
            pass

        predict_proba_holder: list[Any] = []

        def _patch_predict_proba(obj: Any, label: str) -> None:
            if obj is None or not hasattr(obj, "predict_proba"):
                return
            orig = obj.predict_proba

            def pp_wrapped(*args, **kwargs):
                t0 = time.perf_counter()
                try:
                    return orig(*args, **kwargs)
                finally:
                    ExecutionTracer.record(self, "predict_proba", (time.perf_counter() - t0) * 1000, purpose=label)

            obj.predict_proba = pp_wrapped
            predict_proba_holder.append((obj, orig))

        cal_holder: list[Any] = []

        def _patch_calibration(adapter: Any) -> None:
            if adapter is None:
                return
            cal = getattr(adapter, "calibration_adapter", None) or getattr(adapter, "decide", None)
            target = adapter.calibration_adapter if hasattr(adapter, "calibration_adapter") else adapter
            if target is None or not hasattr(target, "decide"):
                return
            orig = target.decide

            def cal_wrapped(ctx):
                t0 = time.perf_counter()
                try:
                    return orig(ctx)
                finally:
                    ExecutionTracer.record(self, "Calibration", (time.perf_counter() - t0) * 1000, purpose="orchestrator+calibration")

            target.decide = cal_wrapped
            cal_holder.append((target, orig))

        try:
            yield self
        finally:
            self._active = False
            for module, name, orig in patches:
                setattr(module, name, orig)
            DataStage.run = orig_data_run
            IndicatorStage.run = orig_ind_run
            for stage_name, (cls, orig_eval) in trend_eval_holder.items():
                cls.evaluate = orig_eval
            for obj, orig in predict_proba_holder:
                obj.predict_proba = orig
            for target, orig in cal_holder:
                target.decide = orig


def stats_from_timings(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0}
    ordered = sorted(values)
    n = len(ordered)

    def pct(p: float) -> float:
        if n == 1:
            return ordered[0]
        return ordered[min(n - 1, int(p * (n - 1)))]

    import statistics

    return {
        "mean_ms": round(statistics.mean(ordered), 4),
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(pct(0.95), 4),
    }
