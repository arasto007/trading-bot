"""Phase 24C — per-stage latency measurement (read-only, no production changes)."""

from __future__ import annotations

import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

PIPELINE_BUDGET_MS = 500.0

STAGE_NAMES = (
    "dataframe_copy",
    "mt5_parquet_read",
    "mt5_fetch_from_broker",
    "data_stage",
    "indicator_stage",
    "pipeline_cache_unified_frame",
    "unified_frame_merge",
    "dataset_store_load",
    "feature_builder_compute_at",
    "range_engine_evaluate",
    "predict_proba_only",
    "trend_engine_evaluate",
    "build_market_context",
    "confidence_engine",
    "decision_orchestrator",
    "calibration",
    "adaptive_risk",
    "trade_quality",
    "profitability_filters",
    "health_gate",
    "legacy_risk_gate",
    "execution_stage_prep",
    "produce_unified_signal_total",
    "kernel_adapter_total",
)


@dataclass
class LatencyStats:
    count: int = 0
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    std_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean_ms": round(self.mean_ms, 4),
            "median_ms": round(self.median_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "p99_ms": round(self.p99_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "std_ms": round(self.std_ms, 4),
        }


@dataclass
class CacheCounters:
    pipeline_feature_hits: int = 0
    pipeline_feature_misses: int = 0
    pipeline_prediction_hits: int = 0
    pipeline_prediction_misses: int = 0
    feature_builder_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        total_feat = self.pipeline_feature_hits + self.pipeline_feature_misses
        total_pred = self.pipeline_prediction_hits + self.pipeline_prediction_misses
        return {
            "pipeline_cache_feature": {
                "hits": self.pipeline_feature_hits,
                "misses": self.pipeline_feature_misses,
                "hit_ratio": round(self.pipeline_feature_hits / total_feat, 4) if total_feat else 0.0,
            },
            "pipeline_cache_prediction": {
                "hits": self.pipeline_prediction_hits,
                "misses": self.pipeline_prediction_misses,
                "hit_ratio": round(self.pipeline_prediction_hits / total_pred, 4) if total_pred else 0.0,
            },
            "feature_builder": {
                "calls": self.feature_builder_calls,
                "internal_cache": False,
                "note": "FeatureBuilder.compute_at has no cache — every call is a full recompute",
            },
        }


@dataclass
class StageRecorder:
    samples: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    cache: CacheCounters = field(default_factory=CacheCounters)

    def record(self, stage: str, elapsed_ms: float) -> None:
        self.samples[stage].append(elapsed_ms)

    def stats(self, stage: str) -> LatencyStats:
        values = self.samples.get(stage, [])
        if not values:
            return LatencyStats()
        ordered = sorted(values)
        n = len(ordered)

        def _pct(p: float) -> float:
            if n == 1:
                return ordered[0]
            idx = min(n - 1, int(p * (n - 1)))
            return ordered[idx]

        return LatencyStats(
            count=n,
            mean_ms=statistics.mean(ordered),
            median_ms=statistics.median(ordered),
            p95_ms=_pct(0.95),
            p99_ms=_pct(0.99),
            max_ms=max(ordered),
            std_ms=statistics.pstdev(ordered) if n > 1 else 0.0,
        )

    def all_stats(self) -> dict[str, dict[str, Any]]:
        return {stage: self.stats(stage).to_dict() for stage in STAGE_NAMES if self.samples.get(stage)}


def _timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000


def _pipeline_feature_cache_hit(
    *,
    symbol: str,
    timeframe: str,
    tail_len: int,
    last_index: Any,
    candles: Any = None,
    base_dir: str | None = None,
) -> bool:
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    if candles is not None:
        cache_key = PipelineCache._build_feature_cache_key(  # noqa: SLF001
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            base_dir=base_dir,
        )
    else:
        cache_key = f"{symbol}:{timeframe}:{tail_len}:{last_index}"
    with PipelineCache._lock:  # noqa: SLF001
        return cache_key in PipelineCache._feature_cache_slots  # noqa: SLF001


def _prediction_cache_hit(row_key: str) -> bool:
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    with PipelineCache._lock:  # noqa: SLF001
        return row_key in PipelineCache._prediction_cache  # noqa: SLF001


def profile_production_pipeline(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int | None = 7,
    tail_only: int | None = None,
    stride: int = 1,
    warmup_bars: int = 250,
    lookback_bars: int = 300,
    measure_mt5: bool = False,
) -> tuple[StageRecorder, dict[str, Any]]:
    """
    Measure every production pipeline stage independently with perf_counter.

    Uses CandleStore shadow replay by default; optionally measures MT5/parquet reads.
    """
    import os

    import pandas as pd
    from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.decision_engine.confidence_engine import ConfidenceEngine
    from tradingbot.ml.decision_engine.orchestrator import DecisionOrchestrator
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.features.builder import FeatureBuilder
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.health_gate import run_pre_decision_health
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.integration.regime_filter_profiles import select_profitability_filter_settings
    from tradingbot.ml.integration.signal_mapper import map_unified_to_trading_signal
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.phase19c.filters import apply_profitability_filters
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.regime_router.phase99_feature_validation import (
        normalize_candles_for_builder,
        ordered_feature_vector,
    )
    from tradingbot.pipeline.data_stage import DataStage
    from tradingbot.pipeline.indicator_stage import IndicatorStage

    legacy = load_legacy_config()
    base_dir = normalize_ml_base_dir(base_dir or legacy.get("BASE_DIR"))
    recorder = StageRecorder()
    meta: dict[str, Any] = {
        "phase": "24C",
        "symbol": symbol,
        "timeframe": timeframe,
        "pipeline_budget_ms": PIPELINE_BUDGET_MS,
        "method": "perf_counter_per_stage",
        "production_modified": False,
    }

    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles_raw is None or candles_raw.empty or dataset is None or dataset.empty:
        meta["error"] = "missing_market_data"
        return recorder, meta

    if tail_only:
        window = normalize_candles_for_builder(candles_raw).tail(tail_only).copy()
    else:
        window = prepare_calibration_candles(candles_raw, days=int(days or 7))

    norm_candles = normalize_candles_for_builder(window)
    market = MarketKey(symbol=symbol, timeframe=timeframe)
    warmup = min(max(warmup_bars, 250), max(0, len(norm_candles) - 2))

    mt5_adapter = None
    if measure_mt5:
        try:
            from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter

            mt5_adapter = Mt5MarketDataAdapter(legacy)
        except Exception as exc:
            meta["mt5_unavailable"] = str(exc)
            measure_mt5 = False

    prev_trend = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()

    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
        ka = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol=symbol))
        range_inner, trend_inner = ka._engine_inners()  # noqa: SLF001
        range_adapter = getattr(range_inner, "inner", range_inner)
        fb = FeatureBuilder(symbol=symbol, base_dir=base_dir)
        bundle = range_adapter.bundle if hasattr(range_adapter, "bundle") else None
        orchestrator = stack.orchestrator.inner if hasattr(stack.orchestrator, "inner") else stack.orchestrator
        confidence_engine = orchestrator.confidence_engine
        cal_adapter = stack.calibration
        risk_adapter = stack.risk
        quality_adapter = stack.quality

        indicators = TechnicalIndicatorEngine(legacy)
        indicator_stage = IndicatorStage(indicators)
        portfolio: dict[str, Any] = {"balance": 10_000, "equity": 10_000, "open_positions": [], "correlation_data": {}}

        if measure_mt5 and mt5_adapter is not None:
            from tradingbot.adapters.market_cache import ParquetCache

            data_dir = legacy.get("data_dir") or legacy.get("DATA_DIR") or "data"
            pq = ParquetCache(data_dir)
            legacy_tf = "5m" if timeframe.upper() == "M5" else timeframe.lower()

            _, parquet_ms = _timed(lambda: pq.load(symbol, legacy_tf))
            recorder.record("mt5_parquet_read", parquet_ms)

            if mt5_adapter._mt5_ready or True:  # noqa: SLF001 — measure fetch path when connected
                try:
                    import asyncio

                    asyncio.run(mt5_adapter.ensure_connected())
                    broker = mt5_adapter._config.get("symbols", [symbol])[0]  # noqa: SLF001
                    from tradingbot.adapters.symbols import resolve_broker_symbol
                    from tradingbot.adapters.timeframes import to_legacy

                    bsym = resolve_broker_symbol(symbol, legacy)
                    ltf = to_legacy(timeframe)
                    _, fetch_ms = _timed(
                        lambda: mt5_adapter._fetch_from_mt5(bsym, ltf, bars=300)  # noqa: SLF001
                    )
                    recorder.record("mt5_fetch_from_broker", fetch_ms)
                except Exception as exc:
                    meta["mt5_fetch_error"] = str(exc)

        for bar_index in range(warmup, len(norm_candles), max(1, stride)):
            chunk, copy_ms = _timed(
                lambda bi=bar_index: norm_candles.iloc[max(0, bi + 1 - lookback_bars) : bi + 1].copy()
            )
            recorder.record("dataframe_copy", copy_ms)
            if len(chunk) < 250:
                continue

            tail = chunk.tail(300)
            cache_key = f"{symbol}:{timeframe}:{len(tail)}:{tail.index[-1]}"
            feat_hit_before = _pipeline_feature_cache_hit(
                symbol=symbol,
                timeframe=timeframe,
                tail_len=len(tail),
                last_index=tail.index[-1],
                candles=tail,
                base_dir=base_dir,
            )

            if measure_mt5 and mt5_adapter is not None:
                from tradingbot.domain.models import CycleContext

                data_stage = DataStage(mt5_adapter, min_bars=80, fetch_bars=300)
                ctx_data = CycleContext(market=market)
                _, data_ms = _timed(lambda: data_stage._market_data.get_ohlcv(market, bars=300))  # noqa: SLF001
                recorder.record("data_stage", data_ms)
            else:
                _, data_ms = _timed(lambda: chunk.copy())
                recorder.record("data_stage", data_ms)

            from tradingbot.domain.models import CycleContext

            ctx_ind = CycleContext(market=market)
            ctx_ind.raw_ohlcv = chunk.copy()

            async def _run_indicator() -> bool:
                return await indicator_stage.run(ctx_ind, portfolio)

            import asyncio

            _, ind_ms = _timed(lambda: asyncio.run(_run_indicator()))
            recorder.record("indicator_stage", ind_ms)

            _, ds_ms = _timed(lambda: DatasetStore(base_dir).load_v2(symbol, timeframe))
            recorder.record("dataset_store_load", ds_ms)

            ds = DatasetStore(base_dir).load_v2(symbol, timeframe)
            _, merge_ms = _timed(lambda: attach_top5_features(build_unified_frame(tail, ds)))
            recorder.record("unified_frame_merge", merge_ms)

            unified, pc_ms = _timed(
                lambda: PipelineCache.get_unified_frame(
                    chunk, base_dir=base_dir, symbol=symbol, timeframe=timeframe
                )
            )
            recorder.record("pipeline_cache_unified_frame", pc_ms)
            if feat_hit_before:
                recorder.cache.pipeline_feature_hits += 1
            else:
                recorder.cache.pipeline_feature_misses += 1

            if unified.empty:
                continue

            row = unified.iloc[-1]
            row_key = f"{symbol}:{timeframe}:{unified.index[-1]}"
            pred_hit = _prediction_cache_hit(row_key)

            bar_idx = len(chunk) - 1
            norm_chunk = normalize_candles_for_builder(chunk)
            _, fb_ms = _timed(lambda: fb.compute_at(norm_chunk, bar_idx))
            recorder.record("feature_builder_compute_at", fb_ms)
            recorder.cache.feature_builder_calls += 1

            _, range_ms = _timed(
                lambda: range_inner.evaluate(
                    row=row, candles=chunk, bar_index=bar_idx, timeframe=timeframe
                )
            )
            recorder.record("range_engine_evaluate", range_ms)

            if bundle is not None:
                feats = fb.compute_at(norm_chunk, bar_idx)
                ordered = ordered_feature_vector(feats, bundle.feature_order)

                def _predict() -> float:
                    return float(bundle.predict_proba(ordered))

                _, prob_ms = _timed(_predict)
                recorder.record("predict_proba_only", prob_ms)

            _, trend_ms = _timed(lambda: trend_inner.evaluate(row, regime=str(row.get("regime", "RANGE"))))
            recorder.record("trend_engine_evaluate", trend_ms)

            ctx, ctx_ms = _timed(
                lambda: build_market_context(
                    row,
                    symbol=symbol,
                    timeframe=timeframe,
                    range_engine=range_inner,
                    trend_engine=trend_inner,
                    candles=chunk,
                    bar_index=bar_idx,
                )
            )
            recorder.record("build_market_context", ctx_ms)

            def _confidence() -> float:
                eng = ctx.range_signal if ctx.regime == "RANGE" else ctx.trend_signal
                return confidence_engine.from_context(ctx, float(eng.confidence))

            _, conf_ms = _timed(_confidence)
            recorder.record("confidence_engine", conf_ms)

            _, orch_ms = _timed(lambda: orchestrator.decide(ctx))
            recorder.record("decision_orchestrator", orch_ms)

            decision = orchestrator.decide(ctx)
            from tradingbot.ml.confidence_engine.validator import raw_confidence_from_decision

            raw_conf = raw_confidence_from_decision(decision, ctx)

            def _calibrate_only() -> Any:
                if hasattr(cal_adapter, "calibrator"):
                    return cal_adapter.calibrator.calibrate(raw_conf)
                if hasattr(cal_adapter, "calibration_method"):
                    return cal_adapter.calibration_method.calibrate(raw_conf)
                return cal_adapter.decide(ctx)

            _, cal_ms = _timed(_calibrate_only)
            recorder.record("calibration", cal_ms)

            def _risk_only() -> Any:
                cal = cal_adapter.decide(ctx)
                mapped = risk_adapter.mapper.map(float(cal.final_confidence))  # noqa: SLF001
                from tradingbot.ml.confidence_mapping.production_adapter import _with_mapped_confidence
                from tradingbot.ml.risk_intelligence.validator import risk_context_from_calibrated

                mapped_cal = _with_mapped_confidence(cal, mapped)
                rctx = risk_context_from_calibrated(
                    ctx, mapped_cal, account=risk_adapter.account, history=risk_adapter.history  # noqa: SLF001
                )
                return risk_adapter.risk_engine.recommend(rctx)  # noqa: SLF001

            _, risk_ms = _timed(_risk_only)
            recorder.record("adaptive_risk", risk_ms)

            _, qual_ms = _timed(lambda: quality_adapter.evaluate(ctx))
            recorder.record("trade_quality", qual_ms)

            calibrated2, risk2, quality2 = quality_adapter.evaluate(ctx)
            filt_settings, _ = select_profitability_filter_settings(
                regime=str(calibrated2.decision.regime),
                engine=str(calibrated2.decision.engine) if calibrated2.decision.engine else None,
            )
            if str(calibrated2.final_action) in ("BUY", "SELL") and risk2.allowed and quality2.allowed:
                _, filt_ms = _timed(
                    lambda: apply_profitability_filters(row.to_dict(), settings=filt_settings)
                )
                recorder.record("profitability_filters", filt_ms)

            _, health_ms = _timed(
                lambda: run_pre_decision_health(registry=stack.registry, base_dir=base_dir, unified_row=row)
            )
            recorder.record("health_gate", health_ms)

            try:
                from tradingbot.adapters.risk_gate import create_risk_gate
                from tradingbot.domain.enums import SignalDirection
                from tradingbot.domain.models import TradingSignal

                rg = create_risk_gate(legacy)
                probe_signal = TradingSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=SignalDirection.BUY,
                    confidence=0.6,
                    strategy_name="latency_probe",
                )
                snap = {**portfolio, "ohlcv": ctx_ind.enriched_ohlcv, "symbol": symbol, "timeframe": timeframe}
                _, rg_ms = _timed(lambda: rg.evaluate(probe_signal, snap))
                recorder.record("legacy_risk_gate", rg_ms)
            except Exception:
                pass

            unified_sig, prod_ms = _timed(lambda: ka.produce_unified_signal(market, chunk))
            recorder.record("produce_unified_signal_total", prod_ms)
            if pred_hit:
                recorder.cache.pipeline_prediction_hits += 1
            else:
                recorder.cache.pipeline_prediction_misses += 1

            trading, exec_ms = _timed(
                lambda: map_unified_to_trading_signal(unified_sig, market, chunk, config=legacy)
            )
            recorder.record("execution_stage_prep", exec_ms)
            del trading

            _, kernel_ms = _timed(lambda: ka.generate_signal(market, chunk, config=legacy))
            recorder.record("kernel_adapter_total", kernel_ms)

    finally:
        if prev_trend is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev_trend

    meta["bars_profiled"] = recorder.stats("produce_unified_signal_total").count
    meta["generated_utc"] = datetime.now(timezone.utc).isoformat()
    return recorder, meta


def build_flamegraph(recorder: StageRecorder) -> dict[str, Any]:
    """Flame-graph style tree using measured p95 latencies."""
    s = recorder.all_stats()

    def _node(name: str, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        st = s.get(name, {})
        return {
            "name": name,
            "p95_ms": st.get("p95_ms", 0.0),
            "mean_ms": st.get("mean_ms", 0.0),
            "count": st.get("count", 0),
            "children": children or [],
        }

    return {
        "phase": "24C",
        "root": _node(
            "kernel_adapter_total",
            [
                _node(
                    "produce_unified_signal_total",
                    [
                        _node("health_gate"),
                        _node(
                            "pipeline_cache_unified_frame",
                            [
                                _node("dataset_store_load"),
                                _node("unified_frame_merge"),
                            ],
                        ),
                        _node(
                            "build_market_context",
                            [
                                _node("range_engine_evaluate", [_node("feature_builder_compute_at"), _node("predict_proba_only")]),
                                _node("trend_engine_evaluate"),
                            ],
                        ),
                        _node(
                            "trade_quality",
                            [
                                _node("calibration", [_node("decision_orchestrator", [_node("confidence_engine")])]),
                                _node("adaptive_risk"),
                            ],
                        ),
                        _node("profitability_filters"),
                    ],
                ),
                _node("execution_stage_prep"),
            ],
        ),
        "kernel_stages_outside_ml": _node(
            "data_path",
            [
                _node("dataframe_copy"),
                _node("data_stage", [_node("mt5_parquet_read"), _node("mt5_fetch_from_broker")]),
                _node("indicator_stage"),
                _node("legacy_risk_gate"),
            ],
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_bottleneck_report(recorder: StageRecorder, meta: dict[str, Any]) -> dict[str, Any]:
    stats = recorder.all_stats()
    total_key = "produce_unified_signal_total"
    total_p95 = stats.get(total_key, {}).get("p95_ms", 0.0)
    total_mean = stats.get(total_key, {}).get("mean_ms", 0.0)

    leaf_stages = [
        "dataframe_copy",
        "data_stage",
        "indicator_stage",
        "pipeline_cache_unified_frame",
        "unified_frame_merge",
        "dataset_store_load",
        "feature_builder_compute_at",
        "range_engine_evaluate",
        "predict_proba_only",
        "trend_engine_evaluate",
        "confidence_engine",
        "decision_orchestrator",
        "calibration",
        "adaptive_risk",
        "trade_quality",
        "profitability_filters",
        "health_gate",
        "legacy_risk_gate",
        "execution_stage_prep",
    ]
    ranked = sorted(
        [(st, stats.get(st, {}).get("p95_ms", 0.0), stats.get(st, {}).get("mean_ms", 0.0)) for st in leaf_stages],
        key=lambda x: x[1],
        reverse=True,
    )
    primary = ranked[0] if ranked else ("none", 0.0, 0.0)
    primary_name, primary_p95, primary_mean = primary

    share_p95 = (primary_p95 / total_p95) if total_p95 > 0 else 0.0
    share_mean = (primary_mean / total_mean) if total_mean > 0 else 0.0

    significant = [
        {"stage": st, "p95_ms": p95, "mean_ms": mean, "share_of_total_p95": round(p95 / total_p95, 4) if total_p95 else 0.0}
        for st, p95, mean in ranked
        if p95 >= 0.05 * total_p95 and p95 > 1.0
    ]

    over_budget = total_p95 > PIPELINE_BUDGET_MS

    if share_p95 >= 0.40:
        verdict = "ONE_BOTTLENECK"
    elif len(significant) >= 2 and significant[0]["share_of_total_p95"] >= 0.20:
        verdict = "MULTIPLE_BOTTLENECKS"
    elif total_p95 <= PIPELINE_BUDGET_MS:
        verdict = "NO_BOTTLENECK_FOUND"
    else:
        verdict = "MULTIPLE_BOTTLENECKS" if len(significant) >= 2 else "ONE_BOTTLENECK"

    return {
        "phase": "24C",
        "pipeline_budget_ms": PIPELINE_BUDGET_MS,
        "total_produce_unified_signal": stats.get(total_key, {}),
        "total_kernel_adapter": stats.get("kernel_adapter_total", {}),
        "over_budget_p95": over_budget,
        "primary_bottleneck": {
            "stage": primary_name,
            "p95_ms": round(primary_p95, 4),
            "mean_ms": round(primary_mean, 4),
            "share_of_total_p95": round(share_p95, 4),
            "share_of_total_mean": round(share_mean, 4),
        },
        "ranked_stages_by_p95": [
            {"rank": i + 1, "stage": st, "p95_ms": round(p95, 4), "mean_ms": round(mean, 4)}
            for i, (st, p95, mean) in enumerate(ranked[:10])
        ],
        "significant_contributors": significant,
        "verdict": verdict,
        "evidence": "All timings from perf_counter — no estimates",
        "meta": {k: v for k, v in meta.items() if k not in ("error",)},
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_optimization_candidates(recorder: StageRecorder, bottleneck: dict[str, Any]) -> dict[str, Any]:
    stats = recorder.all_stats()
    ranked = bottleneck.get("ranked_stages_by_p95", [])
    candidates = []
    for item in ranked:
        st = item["stage"]
        st_stats = stats.get(st, {})
        if st_stats.get("p95_ms", 0) < 1.0:
            continue
        candidates.append(
            {
                "stage": st,
                "p95_ms": st_stats.get("p95_ms"),
                "mean_ms": st_stats.get("mean_ms"),
                "priority": item["rank"],
                "note": "Measurement only — Phase 24C prohibits production changes",
            }
        )
    return {
        "phase": "24C",
        "candidates": candidates,
        "disclaimer": "Read-only investigation — no optimizations applied",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_all_deliverables(
    *,
    base_dir: str | None = None,
    quick: bool = False,
    measure_mt5: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    if quick:
        kwargs.setdefault("tail_only", 320)
        kwargs.setdefault("stride", 4)
        kwargs.setdefault("warmup_bars", 250)

    recorder, meta = profile_production_pipeline(
        base_dir=base_dir,
        measure_mt5=measure_mt5,
        **kwargs,
    )
    stage_timings = recorder.all_stats()
    cache_stats = recorder.cache.to_dict()
    flame = build_flamegraph(recorder)
    bottleneck = build_bottleneck_report(recorder, meta)
    opt = build_optimization_candidates(recorder, bottleneck)

    latency_profile = {
        "phase": "24C",
        "pipeline_budget_ms": PIPELINE_BUDGET_MS,
        "summary": {
            "produce_unified_signal_total": stage_timings.get("produce_unified_signal_total", {}),
            "kernel_adapter_total": stage_timings.get("kernel_adapter_total", {}),
            "feature_builder_compute_at": stage_timings.get("feature_builder_compute_at", {}),
            "pipeline_cache_unified_frame": stage_timings.get("pipeline_cache_unified_frame", {}),
            "unified_frame_merge": stage_timings.get("unified_frame_merge", {}),
            "predict_proba_only": stage_timings.get("predict_proba_only", {}),
            "trade_quality": stage_timings.get("trade_quality", {}),
        },
        "over_budget": bottleneck.get("over_budget_p95", False),
        "meta": meta,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }

    final_report = {
        "phase": "24C",
        "verdict": bottleneck["verdict"],
        "production_modified": False,
        "primary_bottleneck": bottleneck["primary_bottleneck"],
        "pipeline_budget_ms": PIPELINE_BUDGET_MS,
        "total_p95_ms": stage_timings.get("produce_unified_signal_total", {}).get("p95_ms"),
        "total_mean_ms": stage_timings.get("produce_unified_signal_total", {}).get("mean_ms"),
        "cache_statistics": cache_stats,
        "findings": [
            f"Primary bottleneck stage: {bottleneck['primary_bottleneck']['stage']}",
            f"p95 share of produce_unified_signal: {bottleneck['primary_bottleneck']['share_of_total_p95']:.1%}",
            f"Pipeline cache feature hit ratio: {cache_stats['pipeline_cache_feature']['hit_ratio']:.1%}",
            f"FeatureBuilder calls (no internal cache): {cache_stats['feature_builder']['calls']}",
            f"predict_proba_only p95: {stage_timings.get('predict_proba_only', {}).get('p95_ms', 0)} ms",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "latency_profile.json": latency_profile,
        "stage_timings.json": {"phase": "24C", "stages": stage_timings, "meta": meta},
        "cache_statistics.json": {"phase": "24C", **cache_stats, "meta": meta},
        "pipeline_flamegraph.json": flame,
        "bottleneck_report.json": bottleneck,
        "optimization_candidates.json": opt,
        "phase24c_final_report.json": final_report,
    }
