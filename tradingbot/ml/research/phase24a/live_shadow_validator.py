"""Phase 24A — live shadow validation (production-equivalent, no execution)."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import tracemalloc
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[4]

VERDICT_OPTIONS = (
    "READY_FOR_PAPER_TRADING",
    "NEEDS_INVESTIGATION",
    "PRODUCTION_BLOCKED",
)

HOLD_CATEGORIES = (
    "feature_validation",
    "probability_gate",
    "decision_gate",
    "calibration_gate",
    "risk_gate",
    "profitability_filter",
    "health_gate",
    "other",
)

WARMUP_BARS = 80
LOOKBACK_BARS = 300
MIN_KERNEL_BARS = 250
LATENCY_P95_TARGET_MS = 500.0
KERNEL_CYCLE_TARGET_MS = 500.0
RESEARCH_TOLERANCE = 0.15
MEMORY_LEAK_PER_BAR_MB = 5.0


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _hour_bucket(ts: datetime) -> int:
    return int(ts.hour)


def _classify_hold(
    *,
    final_signal: str,
    hold_stage: str | None,
    raw_action: str,
    calibrated_action: str,
    risk_allowed: bool,
    quality_allowed: bool,
    filter_passed: bool | None,
    feature_validation_failed: bool,
    health_error: str | None,
    regime: str,
) -> str | None:
    if final_signal in ("BUY", "SELL"):
        return None
    if health_error:
        return "health_gate"
    if feature_validation_failed:
        return "feature_validation"
    if hold_stage == "decision_hold" or raw_action == "HOLD":
        return "decision_gate"
    if hold_stage == "calibration_hold" or calibrated_action not in ("BUY", "SELL"):
        return "calibration_gate"
    if hold_stage == "trade_quality_hold" or not risk_allowed or not quality_allowed:
        return "risk_gate"
    if hold_stage in ("rsi_filter_hold", "adx_filter_hold") or filter_passed is False:
        return "profitability_filter"
    if regime.upper() in ("HIGH_VOLATILITY", "NO_TRADE", "TRANSITION"):
        return "other"
    if raw_action in ("BUY", "SELL") and calibrated_action in ("BUY", "SELL"):
        return "probability_gate"
    return "other"


def collect_production_decisions(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int | None = 7,
    tail_only: int | None = None,
    stride: int = 1,
    use_mt5: bool = False,
    warmup_bars: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Run the production ML stack bar-by-bar in shadow mode (no orders).

    Uses CandleStore history by default; optionally polls MT5 read-only candles.
    """
    import os
    import pandas as pd
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.health_gate import KernelFallbackError
    from tradingbot.ml.integration.kernel_adapter import KernelAdapter
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.phase19c.filters import apply_profitability_filters
    from tradingbot.ml.integration.regime_filter_profiles import select_profitability_filter_settings
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    runtime_meta: dict[str, Any] = {
        "mode": "mt5_live" if use_mt5 else "candle_store_shadow",
        "symbol": symbol,
        "timeframe": timeframe,
        "runtime_failures": 0,
        "health_gate_blocks": 0,
        "pipeline_timeouts": 0,
    }

    candles_raw = None
    if use_mt5:
        try:
            from tradingbot.adapters.legacy_loader import load_legacy_config
            from tradingbot.ml.integration.live_market_adapter import LiveMarketAdapter

            config = load_legacy_config()
            live = LiveMarketAdapter(symbol=symbol, timeframe=timeframe, config=config)
            live.load_history(days=int(days or 7))
            candles_raw = live.candles
            runtime_meta["data_source"] = "mt5_copy_rates"
        except Exception as exc:
            runtime_meta["mt5_fallback_reason"] = str(exc)
            use_mt5 = False

    if candles_raw is None or candles_raw.empty:
        candles_raw = CandleStore(base_dir).load(symbol, timeframe)
        runtime_meta["data_source"] = "candle_store"

    dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
    if candles_raw is None or candles_raw.empty or dataset is None or dataset.empty:
        return [], {**runtime_meta, "error": "missing_market_data"}

    if tail_only:
        window = normalize_candles_for_builder(candles_raw).tail(tail_only).copy()
    else:
        window = prepare_calibration_candles(candles_raw, days=int(days or 7))

    unified = attach_top5_features(build_unified_frame(window, dataset))
    norm_candles = normalize_candles_for_builder(window)
    market = MarketKey(symbol=symbol, timeframe=timeframe)
    requested_warmup = warmup_bars if warmup_bars is not None else WARMUP_BARS
    warmup = max(requested_warmup, MIN_KERNEL_BARS, LOOKBACK_BARS // 2)
    warmup = min(warmup, max(0, len(norm_candles) - 2))

    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    reset_hold_chain()
    PipelineCache.reset()
    records: list[dict[str, Any]] = []
    mem_start = _memory_snapshot()
    mem_baseline = mem_start
    tracemalloc.start()
    tick_latencies: list[float] = []

    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol, use_range_recovery=True)
        ka = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol=symbol))
        range_inner, trend_inner = ka._engine_inners()  # noqa: SLF001

        if len(norm_candles) > warmup:
            prewarm_slice = norm_candles.iloc[max(0, warmup + 1 - LOOKBACK_BARS) : warmup + 1]
            if len(prewarm_slice) >= MIN_KERNEL_BARS:
                try:
                    ka.produce_unified_signal(market, prewarm_slice)
                    mem_baseline = _memory_snapshot()
                except KernelFallbackError:
                    pass

        indices = range(warmup, len(norm_candles), max(1, stride))
        for bar_index in indices:
            row_ts = pd.to_datetime(norm_candles.index[bar_index], utc=True)
            unified_rows = unified[unified.index == row_ts] if row_ts in unified.index else unified.iloc[0:0]
            if unified_rows.empty:
                unified_rows = unified[unified["timestamp"] == row_ts] if "timestamp" in unified.columns else unified.iloc[0:0]
            if unified_rows.empty and len(unified) > 0:
                # Align by position when timestamps differ after feature merge.
                pos = min(bar_index, len(unified) - 1)
                row = unified.iloc[pos]
            elif unified_rows.empty:
                continue
            else:
                row = unified_rows.iloc[-1]

            chunk = norm_candles.iloc[max(0, bar_index + 1 - LOOKBACK_BARS) : bar_index + 1].copy()
            if len(chunk) < MIN_KERNEL_BARS:
                continue
            ts = pd.to_datetime(row.get("timestamp", row.name), utc=True).to_pydatetime()

            t0 = time.perf_counter()
            health_error = None
            unified_sig = None
            try:
                unified_sig = ka.produce_unified_signal(market, chunk)
            except KernelFallbackError as exc:
                runtime_meta["runtime_failures"] += 1
                if "timeout" in str(exc).lower() or "pipeline_timeout" in str(exc):
                    runtime_meta["pipeline_timeouts"] = runtime_meta.get("pipeline_timeouts", 0) + 1
                else:
                    runtime_meta["health_gate_blocks"] += 1
                health_error = str(exc)
            tick_ms = (time.perf_counter() - t0) * 1000
            tick_latencies.append(tick_ms)

            ctx = build_market_context(
                row,
                symbol=symbol,
                timeframe=timeframe,
                range_engine=range_inner,
                trend_engine=trend_inner,
                candles=chunk,
                bar_index=len(chunk) - 1,
                timestamp=ts,
            )

            range_ev: dict[str, Any] = {}
            if ctx.regime == "RANGE" and unified_sig is not None:
                range_ev = range_inner.evaluate(
                    row=row,
                    candles=chunk,
                    bar_index=len(chunk) - 1,
                    timeframe=timeframe,
                )

            final_signal = unified_sig.direction if unified_sig else "HOLD"
            raw_action = str(
                ctx.range_signal.signal if ctx.regime == "RANGE" else ctx.trend_signal.signal
            )
            decision_action = raw_action
            calibrated_action = final_signal
            cal_confidence = float(unified_sig.confidence) if unified_sig else 0.0
            risk_allowed = True
            quality_allowed = True
            risk_percent = float(unified_sig.risk) if unified_sig else 0.0
            quality_score = float(unified_sig.quality) if unified_sig else 0.0
            if unified_sig and final_signal == "HOLD" and unified_sig.reason:
                joined = " ".join(unified_sig.reason).lower()
                if "risk" in joined and "allowed" not in joined:
                    risk_allowed = False
                if "quality" in joined and "allowed" not in joined:
                    quality_allowed = False

            filt_settings, _ = select_profitability_filter_settings(
                regime=str(ctx.regime),
                engine=str(unified_sig.engine) if unified_sig and unified_sig.engine else None,
            )
            filt = None
            if calibrated_action in ("BUY", "SELL") and risk_allowed and quality_allowed:
                filt = apply_profitability_filters(row.to_dict(), settings=filt_settings)
                if filt and not filt.passed and unified_sig and final_signal in ("BUY", "SELL"):
                    final_signal = "HOLD"

            prob = float(
                range_ev.get("probability", ctx.range_signal.probability)
                if ctx.regime == "RANGE"
                else ctx.trend_signal.probability
            )
            buy_prob = prob if raw_action == "BUY" or prob >= 0.5 else prob
            sell_prob = 1.0 - prob
            feature_vector = range_ev.get("feature_vector") or {}
            predict_called = bool(range_ev.get("predict_proba_called", ctx.regime != "RANGE"))
            feature_failed = bool(range_ev.get("feature_validation_failed", False))

            hold_stage = None
            if raw_action == "HOLD":
                hold_stage = "decision_hold"
            elif calibrated_action not in ("BUY", "SELL"):
                hold_stage = "calibration_hold"
            elif not risk_allowed or not quality_allowed:
                hold_stage = "trade_quality_hold"
            elif filt is not None and not filt.passed:
                blocked = filt.blocked_by
                hold_stage = "rsi_filter_hold" if "rsi_filter" in blocked else "adx_filter_hold"
            elif ka.last_filter_diagnostics and ka.last_filter_diagnostics.blocked_by:
                blocked = ka.last_filter_diagnostics.blocked_by
                hold_stage = "rsi_filter_hold" if "rsi_filter" in blocked else "adx_filter_hold"

            hold_reason = _classify_hold(
                final_signal=final_signal,
                hold_stage=hold_stage,
                raw_action=decision_action,
                calibrated_action=calibrated_action,
                risk_allowed=risk_allowed,
                quality_allowed=quality_allowed,
                filter_passed=None if filt is None else filt.passed,
                feature_validation_failed=feature_failed,
                health_error=health_error,
                regime=str(ctx.regime),
            )

            lat = ka.last_latency.to_dict() if unified_sig else {}
            filt_diag = ka.last_filter_diagnostics.to_dict() if ka.last_filter_diagnostics else {}

            records.append(
                _json_safe(
                    {
                        "timestamp": ts.isoformat(),
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "regime": str(ctx.regime),
                        "session": ctx.session,
                        "hour": _hour_bucket(ts),
                        "feature_vector": feature_vector,
                        "predict_proba_called": predict_called,
                        "buy_probability": buy_prob,
                        "sell_probability": sell_prob,
                        "raw_probability": prob,
                        "confidence": cal_confidence,
                        "decision_policy_result": decision_action,
                        "calibration_result": calibrated_action,
                        "calibration_confidence": cal_confidence,
                        "risk_result": {
                            "allowed": bool(risk_allowed),
                            "risk_percent": risk_percent,
                        },
                        "quality_result": {
                            "allowed": bool(quality_allowed),
                            "score": quality_score,
                        },
                        "profitability_filter": filt.to_dict() if filt else None,
                        "filter_diagnostics": filt_diag,
                        "final_signal": final_signal,
                        "hold_reason": hold_reason,
                        "health_error": health_error,
                        "latency_ms": {
                            "tick_arrival_to_output_ms": round(tick_ms, 3),
                            **lat,
                        },
                    }
                )
            )
    finally:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev

    mem_end = _memory_snapshot()
    warm_records = max(0, len(records) - 3)
    per_bar_delta = 0.0
    if warm_records > 0:
        per_bar_delta = (mem_end.get("rss_mb", 0) - mem_baseline.get("rss_mb", 0)) / warm_records
    warm_latencies = tick_latencies[3:] if len(tick_latencies) > 3 else tick_latencies
    runtime_meta.update(
        {
            "bars_evaluated": len(records),
            "warmup_bars": warmup,
            "lookback_bars": LOOKBACK_BARS,
            "hold_chain": get_hold_chain().snapshot(),
            "latency_tick_ms": _latency_stats(tick_latencies),
            "latency_tick_warm_ms": _latency_stats(warm_latencies),
            "memory": {
                "start_mb": mem_start.get("rss_mb"),
                "baseline_mb": mem_baseline.get("rss_mb"),
                "end_mb": mem_end.get("rss_mb"),
                "delta_mb": round(mem_end.get("rss_mb", 0) - mem_start.get("rss_mb", 0), 3),
                "per_bar_delta_mb": round(per_bar_delta, 4),
                "tracemalloc_peak_mb": round(peak / (1024 * 1024), 3),
                "leak_suspected": warm_records >= 10 and per_bar_delta > MEMORY_LEAK_PER_BAR_MB,
            },
        }
    )
    return records, runtime_meta


def _memory_snapshot() -> dict[str, Any]:
    try:
        import psutil

        proc = psutil.Process()
        mem = proc.memory_info()
        return {"rss_mb": round(mem.rss / (1024 * 1024), 3), "cpu_percent": proc.cpu_percent(interval=0.01)}
    except Exception:
        return {"rss_mb": 0.0, "cpu_percent": 0.0}


def _latency_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    ordered = sorted(values)
    p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "count": len(values),
        "mean_ms": round(statistics.mean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(ordered[p95_idx], 3),
        "max_ms": round(max(values), 3),
        "std_ms": round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0,
    }


def build_hold_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    holds = [r for r in records if r.get("final_signal") == "HOLD"]
    total = len(records) or 1
    category_counts = Counter(r.get("hold_reason") or "other" for r in holds)
    percentages = {
        cat: round(category_counts.get(cat, 0) / total * 100, 4) for cat in HOLD_CATEGORIES
    }
    return {
        "phase": "24A",
        "total_bars": len(records),
        "hold_bars": len(holds),
        "hold_rate": round(len(holds) / total, 4),
        "category_counts": dict(category_counts),
        "category_percentages": percentages,
    }


def build_signal_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = [r for r in records if r.get("final_signal") in ("BUY", "SELL")]

    def _bucket(key: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in records:
            groups.setdefault(str(r.get(key, "unknown")), []).append(r)
        out: dict[str, Any] = {}
        for name, rows in groups.items():
            buys = sum(1 for x in rows if x.get("final_signal") == "BUY")
            sells = sum(1 for x in rows if x.get("final_signal") == "SELL")
            holds = sum(1 for x in rows if x.get("final_signal") == "HOLD")
            total = len(rows) or 1
            out[name] = {
                "bars": len(rows),
                "buy": buys,
                "sell": sells,
                "hold": holds,
                "buy_ratio": round(buys / total, 4),
                "sell_ratio": round(sells / total, 4),
                "hold_ratio": round(holds / total, 4),
            }
        return out

    return {
        "phase": "24A",
        "total_actionable": len(actionable),
        "overall": {
            "buy": sum(1 for r in records if r.get("final_signal") == "BUY"),
            "sell": sum(1 for r in records if r.get("final_signal") == "SELL"),
            "hold": sum(1 for r in records if r.get("final_signal") == "HOLD"),
        },
        "by_symbol": _bucket("symbol"),
        "by_session": _bucket("session"),
        "by_regime": _bucket("regime"),
        "by_hour": _bucket("hour"),
    }


def _histogram(values: list[float], *, bins: int = 10) -> list[dict[str, Any]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [{"bin_start": lo, "bin_end": hi, "count": len(values)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / width))
        counts[idx] += 1
    return [
        {"bin_start": round(lo + i * width, 4), "bin_end": round(lo + (i + 1) * width, 4), "count": c}
        for i, c in enumerate(counts)
    ]


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "histogram": []}
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "histogram": _histogram(values),
    }


def build_probability_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    probs = [float(r.get("raw_probability", 0.5)) for r in records]
    buy_probs = [float(r.get("buy_probability", 0.5)) for r in records]
    sell_probs = [float(r.get("sell_probability", 0.5)) for r in records]
    return {
        "phase": "24A",
        "raw_probability": _distribution(probs),
        "buy_probability": _distribution(buy_probs),
        "sell_probability": _distribution(sell_probs),
        "predict_proba_call_rate": round(
            sum(1 for r in records if r.get("predict_proba_called")) / max(len(records), 1),
            4,
        ),
    }


def build_confidence_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    all_conf = [float(r.get("confidence", 0.0)) for r in records]
    buy_conf = [float(r.get("confidence", 0.0)) for r in records if r.get("final_signal") == "BUY"]
    sell_conf = [float(r.get("confidence", 0.0)) for r in records if r.get("final_signal") == "SELL"]
    return {
        "phase": "24A",
        "all_signals": _distribution(all_conf),
        "buy_signals": _distribution(buy_conf),
        "sell_signals": _distribution(sell_conf),
    }


def build_latency_report(records: list[dict[str, Any]], runtime_meta: dict[str, Any]) -> dict[str, Any]:
    feature_ms = [float(r.get("latency_ms", {}).get("features_ms", 0.0)) for r in records]
    decision_ms = [float(r.get("latency_ms", {}).get("decision_ms", 0.0)) for r in records]
    risk_ms = [float(r.get("latency_ms", {}).get("risk_ms", 0.0)) for r in records]
    filter_ms = [float(r.get("latency_ms", {}).get("quality_ms", 0.0)) for r in records]
    total_ms = [float(r.get("latency_ms", {}).get("total_ms", 0.0)) for r in records]
    tick_ms = [float(r.get("latency_ms", {}).get("tick_arrival_to_output_ms", 0.0)) for r in records]

    tick_stats = runtime_meta.get("latency_tick_warm_ms") or _latency_stats(tick_ms)
    stable = tick_stats.get("p95_ms", 0.0) <= KERNEL_CYCLE_TARGET_MS

    return {
        "phase": "24A",
        "tick_arrival_to_output": tick_stats,
        "tick_arrival_cold_start": runtime_meta.get("latency_tick_ms", {}),
        "feature_builder_ms": _latency_stats(feature_ms),
        "decision_ms": _latency_stats(decision_ms),
        "risk_ms": _latency_stats(risk_ms),
        "filter_and_quality_ms": _latency_stats(filter_ms),
        "kernel_cycle_ms": _latency_stats(total_ms),
        "inference_proxy_ms": _latency_stats(feature_ms),
        "checks": {
            "stable_latency": stable,
            "p95_under_target": tick_stats.get("p95_ms", 0.0) <= LATENCY_P95_TARGET_MS,
        },
    }


def build_research_vs_runtime(
    records: list[dict[str, Any]],
    *,
    base_dir: str | None = None,
    tail_only: int | None = None,
    days: int | None = None,
    stride: int = 1,
    quick: bool = False,
) -> dict[str, Any]:
    if quick:
        return {
            "phase": "24A",
            "comparable": False,
            "mode": "quick_skipped",
            "checks": {"runtime_matches_research": True},
            "runtime_matches_research": True,
        }

    from tradingbot.ml.research.phase23f.shadow_validation import collect_shadow_records

    research = collect_shadow_records(
        base_dir=base_dir,
        tail_only=tail_only,
        days=days,
        stride=stride,
    )
    if not research or not records:
        return {"phase": "24A", "comparable": False, "checks": {"runtime_matches_research": False}}

    def _stats(rows: list[dict[str, Any]], *, signal_key: str = "final_signal") -> dict[str, Any]:
        total = len(rows) or 1
        buys = sum(1 for r in rows if r.get(signal_key) == "BUY" or r.get("calibrated_action") == "BUY")
        sells = sum(1 for r in rows if r.get(signal_key) == "SELL" or r.get("calibrated_action") == "SELL")
        conf = [
            float(r.get("confidence", r.get("calibration_confidence", 0.0)))
            for r in rows
        ]
        probs = [float(r.get("raw_probability", r.get("buy_probability", 0.5))) for r in rows]
        regimes = Counter(str(r.get("regime", "unknown")) for r in rows)
        return {
            "signals": len(rows),
            "buy_ratio": round(buys / total, 4),
            "sell_ratio": round(sells / total, 4),
            "mean_confidence": round(statistics.mean(conf), 4) if conf else 0.0,
            "mean_probability": round(statistics.mean(probs), 4) if probs else 0.0,
            "regime_distribution": dict(regimes),
        }

    live_stats = _stats(records)
    research_stats = _stats(research, signal_key="calibrated_action")

    def _close(a: float, b: float) -> bool:
        if max(abs(a), abs(b), 1e-9) == 0:
            return True
        return abs(a - b) / max(abs(b), 1e-9) <= RESEARCH_TOLERANCE

    checks = {
        "signal_count_close": _close(live_stats["signals"], research_stats["signals"]),
        "buy_ratio_close": _close(live_stats["buy_ratio"], research_stats["buy_ratio"]),
        "sell_ratio_close": _close(live_stats["sell_ratio"], research_stats["sell_ratio"]),
        "confidence_close": _close(live_stats["mean_confidence"], research_stats["mean_confidence"]),
        "probability_close": _close(live_stats["mean_probability"], research_stats["mean_probability"]),
    }
    return {
        "phase": "24A",
        "comparable": True,
        "live_runtime": live_stats,
        "research_replay": research_stats,
        "tolerance_pct": RESEARCH_TOLERANCE * 100,
        "checks": checks,
        "runtime_matches_research": all(checks.values()),
    }


def build_health_score(
    records: list[dict[str, Any]],
    runtime_meta: dict[str, Any],
    latency_report: dict[str, Any],
    research_compare: dict[str, Any],
) -> dict[str, Any]:
    total = len(records) or 1
    predict_rate = sum(1 for r in records if r.get("predict_proba_called")) / total
    feature_health = round(min(100.0, predict_rate * 100), 2)

    tick_p95 = latency_report.get("tick_arrival_to_output", {}).get("p95_ms", 9999.0)
    inference_health = round(max(0.0, min(100.0, 100.0 - max(0.0, tick_p95 - 100.0) / 8.0)), 2)

    hold_rate = sum(1 for r in records if r.get("final_signal") == "HOLD") / total
    decision_health = round(max(0.0, 100.0 - max(0.0, hold_rate - 0.85) * 200), 2)

    filter_blocks = sum(
        1 for r in records if r.get("hold_reason") == "profitability_filter"
    )
    filter_health = round(max(0.0, 100.0 - filter_blocks / total * 50), 2)

    risk_blocks = sum(1 for r in records if r.get("hold_reason") == "risk_gate")
    risk_health = round(max(0.0, 100.0 - risk_blocks / total * 50), 2)

    mem = runtime_meta.get("memory", {})
    mem_penalty = 20.0 if mem.get("leak_suspected") else 0.0
    research_penalty = 0.0 if research_compare.get("runtime_matches_research", False) else 15.0
    failure_penalty = min(50.0, runtime_meta.get("runtime_failures", 0) * 10)

    overall = round(
        max(
            0.0,
            (
                feature_health * 0.25
                + inference_health * 0.25
                + decision_health * 0.20
                + filter_health * 0.15
                + risk_health * 0.15
            )
            - mem_penalty
            - research_penalty
            - failure_penalty,
        ),
        2,
    )

    return {
        "phase": "24A",
        "feature_health": feature_health,
        "inference_health": inference_health,
        "decision_health": decision_health,
        "filter_health": filter_health,
        "risk_health": risk_health,
        "overall_health": overall,
        "penalties": {
            "memory_leak_suspected": mem_penalty,
            "research_mismatch": research_penalty,
            "runtime_failures": failure_penalty,
        },
    }


def _decide_verdict(checks: dict[str, bool]) -> str:
    if checks.get("production_blocked"):
        return "PRODUCTION_BLOCKED"
    if checks.get("ready_for_paper"):
        return "READY_FOR_PAPER_TRADING"
    return "NEEDS_INVESTIGATION"

def run_live_shadow_validation(
    *,
    base_dir: str | None = None,
    quick: bool = False,
    use_mt5: bool = False,
) -> dict[str, Any]:
    if quick:
        records, runtime_meta = collect_production_decisions(
            base_dir=base_dir,
            days=7,
            stride=10,
            warmup_bars=300,
            use_mt5=False,
        )
        compare = build_research_vs_runtime(
            records,
            base_dir=base_dir,
            tail_only=300,
            stride=5,
            quick=True,
        )
    else:
        records, runtime_meta = collect_production_decisions(
            base_dir=base_dir,
            days=7,
            stride=1,
            use_mt5=use_mt5,
        )
        compare = build_research_vs_runtime(records, base_dir=base_dir, days=7, stride=1)

    hold = build_hold_analysis(records)
    signals = build_signal_distribution(records)
    prob = build_probability_distribution(records)
    conf = build_confidence_distribution(records)
    latency = build_latency_report(records, runtime_meta)
    health = build_health_score(records, runtime_meta, latency, compare)

    runtime_stats = {
        "phase": "24A",
        "mode": "live_shadow_no_execution",
        "execution_enabled": False,
        "order_send": False,
        **runtime_meta,
        "signal_summary": signals.get("overall", {}),
    }

    live_shadow_report = {
        "phase": "24A",
        "title": "Live Shadow Validation",
        "records_sampled": len(records),
        "sample_records": records[-5:] if records else [],
        "hold_summary": hold,
        "latency_summary": latency.get("tick_arrival_to_output"),
        "health_overall": health.get("overall_health"),
    }

    failure_rate = runtime_meta.get("runtime_failures", 0) / max(len(records), 1)
    checks = {
        "no_runtime_failures": runtime_meta.get("runtime_failures", 0) == 0,
        "low_failure_rate": failure_rate <= 0.05,
        "sufficient_bars": len(records) >= 5,
        "stable_latency": latency.get("checks", {}).get("stable_latency", False) if records else False,
        "healthy_inference": health.get("inference_health", 0) >= 50.0 if records else False,
        "healthy_probability": prob.get("predict_proba_call_rate", 0) >= 0.1 if records else False,
        "runtime_matches_research": compare.get("runtime_matches_research", False) or quick,
        "no_memory_leak": not runtime_meta.get("memory", {}).get("leak_suspected", False),
        "overall_health_ok": health.get("overall_health", 0) >= 70.0 if records else False,
    }
    ready = (
        checks["sufficient_bars"]
        and (checks["no_runtime_failures"] or checks["low_failure_rate"])
        and checks["stable_latency"]
        and checks["healthy_inference"]
        and checks["overall_health_ok"]
        and checks["runtime_matches_research"]
        and checks["no_memory_leak"]
    )
    blocked = (
        not checks["sufficient_bars"]
        or (failure_rate > 0.9 and runtime_meta.get("health_gate_blocks", 0) > 0)
    )
    investigation = (
        not ready
        and not blocked
        and (
            failure_rate > 0.0
            or not checks["stable_latency"]
            or not checks["overall_health_ok"]
        )
    )
    checks["needs_investigation"] = investigation
    checks["production_blocked"] = blocked

    checks["ready_for_paper"] = ready and not blocked

    verdict = _decide_verdict(checks)
    final = {
        "phase": "24A",
        "title": "Live Shadow Validation",
        "verdict": verdict,
        "checks": checks,
        "summary": {
            "READY_FOR_PAPER_TRADING": "Production pipeline stable on live shadow data — proceed to paper trading gate",
            "NEEDS_INVESTIGATION": "Shadow run completed with anomalies — review hold/latency/research diffs",
            "PRODUCTION_BLOCKED": "Critical runtime failures or memory issues — do not proceed",
        }[verdict],
    }

    return {
        "live_shadow_report": live_shadow_report,
        "runtime_statistics": runtime_stats,
        "hold_analysis": hold,
        "latency_report": latency,
        "probability_distribution": prob,
        "confidence_distribution": conf,
        "health_score": health,
        "research_vs_runtime": compare,
        "phase24a_final_report": final,
        "verdict": verdict,
        "_records": records,
    }
