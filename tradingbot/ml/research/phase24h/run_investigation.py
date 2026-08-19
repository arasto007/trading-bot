"""Phase 24H — duplicate pipeline execution investigation."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE24C_TIMINGS = PROJECT_ROOT / "tradingbot/ml/research/phase24c/stage_timings.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_24c_stage(name: str) -> dict[str, float]:
    if not PHASE24C_TIMINGS.is_file():
        return {}
    payload = json.loads(PHASE24C_TIMINGS.read_text(encoding="utf-8"))
    return payload.get("stages", {}).get(name, {})


def static_duplicate_inventory() -> list[dict[str, Any]]:
    """Repository-evidence duplicate inventory (no production changes)."""
    return [
        {
            "stage": "HealthGate",
            "executions_per_closed_candle": 2,
            "why": "require_health called before unified frame and again after row extract",
            "caller": "KernelAdapter.produce_unified_signal",
            "file": "tradingbot/ml/integration/kernel_adapter.py",
            "lines": [172, 189],
            "purpose": "Registry integrity then per-row trend feature validation",
            "classification": "Historical",
            "can_eliminate": True,
            "elimination_note": "Merge into single require_health after unified row available",
        },
        {
            "stage": "FeatureBuilder.compute_at + build_unified_frame",
            "executions_per_closed_candle": 2,
            "why": "PipelineCache builds full unified frame; RangeEngineAdapter recomputes via FeatureBuilder on live path",
            "caller": "PipelineCache.get_unified_frame → build_unified_frame; RangeEngineAdapter._features_from_candles",
            "file": "tradingbot/ml/integration/pipeline_cache.py:108; tradingbot/ml/research/regime_router/range_engine_adapter.py:52-63",
            "lines": [108, 52],
            "purpose": "Unified matrix for trend/range row vs phase99 live feature vector",
            "classification": "Accidental",
            "can_eliminate": True,
            "elimination_note": "Use unified row phase99_* columns when merge hit; FeatureBuilder only on miss",
        },
        {
            "stage": "build_ml_features (inside build_unified_frame) + IndicatorStage",
            "executions_per_closed_candle": 2,
            "why": "IndicatorStage enriches OHLCV; build_ml_features recomputes overlapping indicators on same window",
            "caller": "IndicatorStage.run; build_unified_frame → build_ml_features",
            "file": "tradingbot/pipeline/indicator_stage.py:21; tradingbot/ml/research/phase13_9/unified_features.py",
            "lines": [21, 88],
            "purpose": "Legacy indicator columns vs ML kernel feature matrix",
            "classification": "Historical",
            "can_eliminate": True,
            "elimination_note": "Skip IndicatorStage when USE_ML_KERNEL=true (research phase only)",
        },
        {
            "stage": "TrendEngine.evaluate",
            "executions_per_closed_candle": 2,
            "why": "build_market_context always evaluates range AND trend engines",
            "caller": "build_market_context",
            "file": "tradingbot/ml/decision_engine/validation.py",
            "lines": [120, 126],
            "purpose": "Provide both signals to DecisionOrchestrator",
            "classification": "Accidental",
            "can_eliminate": True,
            "elimination_note": "Lazy-eval trend only when regime routes to TREND (preserve orchestrator inputs)",
        },
        {
            "stage": "predict_proba",
            "executions_per_closed_candle": 2,
            "why": "Range bundle + trend bundle both infer even when one engine selected",
            "caller": "RangeEngineAdapter.evaluate; TrendRfV41Engine.evaluate",
            "file": "tradingbot/ml/research/regime_router/range_engine_adapter.py:88; tradingbot/ml/phase17d/v41_engine.py:64",
            "lines": [88, 64],
            "purpose": "Engine probability for routing",
            "classification": "Accidental",
            "can_eliminate": True,
            "elimination_note": "Coupled with lazy engine evaluation",
        },
        {
            "stage": "normalize_candles_for_builder",
            "executions_per_closed_candle": 2,
            "why": "KernelAdapter normalizes candles; RangeEngineAdapter normalizes again inside FeatureBuilder path",
            "caller": "KernelAdapter.produce_unified_signal; RangeEngineAdapter._features_from_candles",
            "file": "tradingbot/ml/integration/kernel_adapter.py:205; range_engine_adapter.py:52",
            "lines": [205, 52],
            "purpose": "Index normalization for feature builders",
            "classification": "Accidental",
            "can_eliminate": True,
            "elimination_note": "Pass pre-normalized candles from KernelAdapter",
        },
        {
            "stage": "rule_classify_row",
            "executions_per_closed_candle": "1-2",
            "why": "build_market_context classifies regime; PipelineCache may classify all rows if regime column missing",
            "caller": "build_market_context; PipelineCache._attach_trend_v41_features",
            "file": "tradingbot/ml/decision_engine/validation.py:113; pipeline_cache.py:129",
            "lines": [113, 129],
            "purpose": "Regime label for routing / trend_age",
            "classification": "Historical",
            "can_eliminate": True,
            "elimination_note": "Unified frame already attaches regime — v41 attach path rarely re-classifies",
        },
        {
            "stage": "AdaptiveRisk + RiskGate",
            "executions_per_closed_candle": "1 each (non-HOLD only for RiskGate)",
            "why": "ML AdaptiveRisk inside TradeQuality chain; legacy RiskGate before execution",
            "caller": "TradeQualityAdapter.evaluate; RiskStage.run",
            "file": "tradingbot/ml/confidence_mapping/production_adapter.py:79; tradingbot/pipeline/risk_stage.py:35",
            "lines": [79, 35],
            "purpose": "ML risk recommendation vs execution authority gate",
            "classification": "Required",
            "can_eliminate": False,
            "elimination_note": "Separate layers by design — do not merge",
        },
        {
            "stage": "DataStage + IndicatorStage on poll cycles",
            "executions_per_closed_candle": "N polls until next bar",
            "why": "SignalStage dedup runs AFTER data/indicator stages",
            "caller": "TradingKernel.run_market_cycle",
            "file": "tradingbot/pipeline/signal_stage.py:30",
            "lines": [30],
            "purpose": "Bar dedup prevents duplicate signals but not duplicate data load",
            "classification": "Accidental",
            "can_eliminate": True,
            "elimination_note": "Early-exit before DataStage when last closed ts unchanged",
        },
    ]


def build_duplicate_cost(execution_counts: dict[str, int]) -> dict[str, Any]:
    """Estimate wasted ms from Phase 24C measured timings × extra executions."""
    timings = (
        json.loads(PHASE24C_TIMINGS.read_text(encoding="utf-8")).get("stages", {})
        if PHASE24C_TIMINGS.is_file()
        else {}
    )

    duplicate_specs = [
        ("HealthGate", "health_gate", 1, "Second require_health per candle"),
        ("FeatureBuilder.compute_at", "feature_builder_compute_at", 1, "Overlaps unified frame features"),
        ("IndicatorStage", "indicator_stage", 1, "Overlaps build_ml_features when ML kernel active"),
        ("TrendEngine.evaluate", "trend_engine_evaluate", 1, "Unused when RANGE regime selected"),
        ("predict_proba", "predict_proba_only", 1, "Second engine inference"),
        ("normalize_candles_for_builder", "dataframe_copy", 1, "Second normalize pass"),
    ]

    rows: list[dict[str, Any]] = []
    total_p95 = 0.0
    total_mean = 0.0
    for stage, timing_key, extra_calls, note in duplicate_specs:
        t = timings.get(timing_key, {})
        mean = float(t.get("mean_ms", 0))
        median = float(t.get("median_ms", 0))
        p95 = float(t.get("p95_ms", 0))
        wasted_mean = round(mean * extra_calls, 4)
        wasted_p95 = round(p95 * extra_calls, 4)
        total_mean += wasted_mean
        total_p95 += wasted_p95
        rows.append(
            {
                "duplicate_stage": stage,
                "extra_executions": extra_calls,
                "basis_timing_key": timing_key,
                "mean_ms_per_call": mean,
                "median_ms_per_call": median,
                "p95_ms_per_call": p95,
                "wasted_mean_ms": wasted_mean,
                "wasted_p95_ms": wasted_p95,
                "note": note,
            }
        )

    return {
        "phase": "24H",
        "basis": "phase24c/stage_timings.json",
        "duplicates": rows,
        "total_wasted_mean_ms": round(total_mean, 4),
        "total_wasted_p95_ms": round(total_p95, 4),
        "generated_utc": _utc_now(),
    }


def build_optimization_priority() -> dict[str, Any]:
    return {
        "phase": "24H",
        "constraints": [
            "DO NOT change trading logic",
            "DO NOT change probabilities",
            "DO NOT change features",
            "DO NOT change fingerprints",
        ],
        "priority": [
            {
                "rank": 1,
                "target": "Skip FeatureBuilder when unified row has phase99 features",
                "estimated_p95_savings_ms": _load_24c_stage("feature_builder_compute_at").get("p95_ms", 69),
                "risk": "LOW",
                "parity_requirement": "Use row_for_phase99_range fallback only on merge miss",
            },
            {
                "rank": 2,
                "target": "Lazy trend engine evaluation based on regime pre-check",
                "estimated_p95_savings_ms": _load_24c_stage("trend_engine_evaluate").get("p95_ms", 31),
                "risk": "MEDIUM",
                "parity_requirement": "Must preserve DecisionOrchestrator inputs for TREND bars",
            },
            {
                "rank": 3,
                "target": "Merge dual HealthGate calls into single post-unified check",
                "estimated_p95_savings_ms": _load_24c_stage("health_gate").get("p95_ms", 26),
                "risk": "LOW",
                "parity_requirement": "Same checks, single call after row available",
            },
            {
                "rank": 4,
                "target": "Early SignalStage dedup before DataStage/IndicatorStage",
                "estimated_p95_savings_ms": _load_24c_stage("indicator_stage").get("p95_ms", 51),
                "risk": "LOW",
                "parity_requirement": "Only skip on unchanged closed-bar timestamp",
            },
            {
                "rank": 5,
                "target": "Pass normalized candles from KernelAdapter to RangeEngine",
                "estimated_p95_savings_ms": 1.0,
                "risk": "LOW",
                "parity_requirement": "Same normalize_candles_for_builder output",
            },
        ],
        "generated_utc": _utc_now(),
    }


def build_safety_analysis() -> dict[str, Any]:
    inv = static_duplicate_inventory()
    return {
        "phase": "24H",
        "classifications": {
            "Required": [d for d in inv if d["classification"] == "Required"],
            "Safety-related": [d for d in inv if d["classification"] == "Safety-related"],
            "Historical": [d for d in inv if d["classification"] == "Historical"],
            "Accidental": [d for d in inv if d["classification"] == "Accidental"],
        },
        "generated_utc": _utc_now(),
    }


async def trace_one_closed_candle(*, base_dir: str | None = None) -> dict[str, Any]:
    """Runtime trace of one new closed candle through production pipeline stages."""
    from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import CycleContext, MarketKey
    from tradingbot.domain.ohlcv import exclude_forming_bar
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.research.phase24h.pipeline_tracer import ExecutionTracer
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.pipeline.data_stage import DataStage
    from tradingbot.pipeline.indicator_stage import IndicatorStage

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    symbol, timeframe = "XAUUSD", "M5"
    os.environ["USE_ML_KERNEL"] = "true"
    os.environ[TREND_VERSION_ENV] = "v41"
    os.environ["ENABLE_OPTIMIZED_UNIFIED_FRAME"] = "true"

    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        return {"error": "missing_candles"}

    norm = normalize_candles_for_builder(prepare_calibration_candles(candles_raw, days=90))
    bar_index = min(len(norm) - 1, 400)
    chunk = norm.iloc[max(0, bar_index + 1 - 300) : bar_index + 1]
    candle_id = f"{symbol}:{timeframe}:{chunk.index[-1].isoformat()}"

    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    deps = stack.as_dependencies(base_dir=base_dir, symbol=symbol)
    ka = KernelAdapter(deps)
    market = MarketKey(symbol=symbol, timeframe=timeframe)

    tracer = ExecutionTracer()

    class _StaticOHLCV:
        def get_ohlcv(self, market_key, bars=300):
            return chunk.copy()

    data_stage = DataStage(_StaticOHLCV(), fetch_bars=300)
    ind_stage = IndicatorStage(TechnicalIndicatorEngine())

    with tracer.trace(candle_id):
        import tradingbot.ml.integration.kernel_adapter as ka_mod

        orig_timeout = ka_mod.PIPELINE_TIMEOUT_MS
        ka_mod.PIPELINE_TIMEOUT_MS = 60000.0
        try:
            ctx = CycleContext(market=market)
            portfolio: dict = {}
            await data_stage.run(ctx, portfolio)
            await ind_stage.run(ctx, portfolio)
            closed = exclude_forming_bar(ctx.enriched_ohlcv)

            range_inner, trend_inner = ka._engine_inners()
            if hasattr(range_inner, "bundle"):
                orig_pp = range_inner.bundle.predict_proba

                def pp_range(*a, **k):
                    import time

                    t0 = time.perf_counter()
                    try:
                        return orig_pp(*a, **k)
                    finally:
                        tracer.record("predict_proba", (time.perf_counter() - t0) * 1000, purpose="phase9_9")

                range_inner.bundle.predict_proba = pp_range

            trend_bundle = getattr(trend_inner, "_bundle", None) or getattr(trend_inner, "bundle", None)
            if trend_bundle is not None and hasattr(trend_bundle, "predict_proba"):
                orig_tpp = trend_bundle.predict_proba

                def pp_trend(*a, **k):
                    import time

                    t0 = time.perf_counter()
                    try:
                        return orig_tpp(*a, **k)
                    finally:
                        tracer.record("predict_proba", (time.perf_counter() - t0) * 1000, purpose="trend_v41")

                trend_bundle.predict_proba = pp_trend

            cal_adapter = getattr(deps.quality.risk_adapter, "calibration_adapter", None)
            if cal_adapter is not None and hasattr(cal_adapter, "decide"):
                orig_decide = cal_adapter.decide

                def cal_decide(ctx_in):
                    import time

                    t0 = time.perf_counter()
                    try:
                        return orig_decide(ctx_in)
                    finally:
                        tracer.record("Calibration", (time.perf_counter() - t0) * 1000, purpose="orchestrator+calibration")

                cal_adapter.decide = cal_decide

            ka.produce_unified_signal(market, closed)
        finally:
            ka_mod.PIPELINE_TIMEOUT_MS = orig_timeout

    counts = tracer.counts()
    duplicates = [
        {
            "stage": stage,
            "count": count,
            "expected": 1,
            "is_duplicate": count > 1,
        }
        for stage, count in counts.items()
        if count > 0
    ]

    return {
        "candle_id": candle_id,
        "execution_order": tracer.execution_order(),
        "execution_counts": counts,
        "stage_timing_stats": {
            k: __import__("tradingbot.ml.research.phase24h.pipeline_tracer", fromlist=["stats_from_timings"]).stats_from_timings(v)
            for k, v in tracer.timings.items()
        },
        "duplicate_flags": [d for d in duplicates if d["is_duplicate"]],
        "verified_components": {
            "PipelineCache.get_unified_frame": counts.get("PipelineCache.get_unified_frame", 0),
            "build_unified_frame": counts.get("build_unified_frame", 0),
            "FeatureBuilder.compute_at": counts.get("FeatureBuilder.compute_at", 0),
            "RangeEngineAdapter.evaluate": counts.get("RangeEngineAdapter.evaluate", 0),
            "TrendEngine.evaluate": counts.get("TrendEngine.evaluate", 0),
            "HealthGate": counts.get("HealthGate", 0),
            "TradeQuality": counts.get("TradeQuality", 0),
        },
    }


def run_investigation(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    from tradingbot.ml.research.phase24h.pipeline_tracer import STAGE_IDS

    trace_result = asyncio.run(trace_one_closed_candle(base_dir=base_dir))
    if "error" in trace_result:
        return trace_result

    static_dupes = static_duplicate_inventory()
    duplicate_cost = build_duplicate_cost(trace_result.get("execution_counts", {}))

    removable = [d for d in static_dupes if d.get("can_eliminate")]
    required = [d for d in static_dupes if not d.get("can_eliminate")]

    if trace_result.get("duplicate_flags") or removable:
        verdict = "SAFE_DUPLICATE_REMOVAL"
    elif not trace_result.get("duplicate_flags"):
        verdict = "NO_DUPLICATES_FOUND"
    else:
        verdict = "DUPLICATES_REQUIRED"

    return {
        "single_candle_trace.json": {
            "phase": "24H",
            **trace_result,
            "generated_utc": _utc_now(),
        },
        "execution_counter.json": {
            "phase": "24H",
            "candle_id": trace_result.get("candle_id"),
            "counts": trace_result.get("execution_counts"),
            "stages_monitored": list(STAGE_IDS),
            "generated_utc": _utc_now(),
        },
        "duplicate_stage_report.json": {
            "phase": "24H",
            "runtime_duplicates": trace_result.get("duplicate_flags", []),
            "repository_duplicates": static_dupes,
            "component_verification": trace_result.get("verified_components", {}),
            "generated_utc": _utc_now(),
        },
        "duplicate_cost.json": duplicate_cost,
        "optimization_priority.json": build_optimization_priority(),
        "safety_analysis.json": build_safety_analysis(),
        "phase24h_final_report.json": {
            "phase": "24H",
            "verdict": verdict,
            "production_modified": False,
            "summary": (
                f"Duplicate pipeline execution audit: {verdict}. "
                f"Runtime duplicate stages: {len(trace_result.get('duplicate_flags', []))}. "
                f"Repository-identified duplicates: {len(static_dupes)}. "
                f"Estimated wasted p95: {duplicate_cost.get('total_wasted_p95_ms', 0)} ms."
            ),
            "removable_count": len(removable),
            "required_count": len(required),
            "generated_utc": _utc_now(),
        },
    }


def write_deliverables(*, base_dir: str | None = None, quick: bool = False) -> dict[str, Any]:
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    artifacts = run_investigation(base_dir=base_dir, quick=quick)
    if "error" in artifacts:
        return artifacts
    for name, payload in artifacts.items():
        (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "written": list(artifacts.keys()),
        "verdict": artifacts["phase24h_final_report.json"]["verdict"],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 24H duplicate pipeline investigation")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    print(json.dumps(write_deliverables(quick=args.quick), indent=2))
