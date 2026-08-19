"""Phase 27D metrics — measured production behavior after cache fix."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

from tradingbot.ml.research.phase27a.metrics import (
    _calmar,
    _engine_norm,
    _histogram,
    _mean,
    _median,
    _regime_norm,
    _safe_pct,
    build_decision_analysis,
    build_engine_analysis,
    build_hold_analysis,
    build_journal_integrity,
    build_latency_analysis,
    build_profitability_metrics,
    build_regime_analysis,
    build_risk_analysis,
    build_system_health,
    build_trade_statistics,
    classify_hold,
)
from tradingbot.ml.research.phase26b.analyzers import _profit_factor


def _session_from_ts(ts: str) -> str:
    try:
        import pandas as pd

        hour = pd.Timestamp(ts).hour
        if hour < 6:
            return "rollover"
        if hour < 12:
            return "london"
        if hour < 17:
            return "new_york"
        return "off_hours"
    except Exception:
        return "unknown"


def _dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "p95": round(p95, 6),
    }


def build_trading_statistics(
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    replay_days: int,
) -> dict[str, Any]:
    base = build_trade_statistics(trades, records, replay_days=replay_days)
    sessions: Counter[str] = Counter()
    for t in trades:
        sessions[_session_from_ts(str(t.get("timestamp", "")))] += 1
    weeks = max(replay_days / 7.0, 1.0)
    return {
        **base,
        "trades_per_week": round(len(trades) / weeks, 4),
        "trades_per_session": dict(sessions),
        "average_duration_bars": base.get("average_trade_duration_bars"),
        "average_duration_sec": round(
            _mean([float(t.get("duration_sec") or 0) for t in trades]), 2
        )
        if trades
        else 0.0,
    }


def build_performance_statistics(
    trades: list[dict[str, Any]],
    profitability: dict[str, Any],
    *,
    replay_days: int,
) -> dict[str, Any]:
    return {
        "completed_trades": len(trades),
        "replay_days": replay_days,
        "net_profit": profitability.get("total_net_profit"),
        "profit_factor": profitability.get("profit_factor"),
        "expectancy": profitability.get("expectancy"),
        "win_rate_pct": _safe_pct(
            sum(1 for t in trades if float(t["pnl"]) > 0), len(trades)
        ),
        "sharpe_ratio": profitability.get("sharpe_ratio"),
        "sortino_ratio": profitability.get("sortino_ratio"),
        "calmar_ratio": profitability.get("calmar_ratio"),
        "max_drawdown_pct": profitability.get("max_drawdown_pct"),
        "recovery_factor": profitability.get("recovery_factor"),
        "final_equity": profitability.get("final_equity"),
    }


def build_profitability_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    prof = build_profitability_metrics(trades)
    mae = _mean([float(t["mae"]) for t in trades])
    mfe = _mean([float(t["mfe"]) for t in trades])
    return {
        "gross_profit": prof.get("gross_profit"),
        "gross_loss": prof.get("gross_loss"),
        "net_profit": prof.get("total_net_profit"),
        "profit_factor": prof.get("profit_factor"),
        "expectancy": prof.get("expectancy"),
        "average_rr": prof.get("average_rr"),
        "average_win": prof.get("average_win"),
        "average_loss": prof.get("average_loss"),
        "average_mae": mae,
        "average_mfe": mfe,
        "maximum_drawdown_pct": prof.get("max_drawdown_pct"),
        "maximum_drawdown_abs": prof.get("max_drawdown_abs"),
        "sharpe": prof.get("sharpe_ratio"),
        "sortino": prof.get("sortino_ratio"),
        "calmar": prof.get("calmar_ratio"),
        "recovery_factor": prof.get("recovery_factor"),
    }


def build_signal_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    conf = [float(r.get("confidence") or 0) for r in records]
    probs = conf  # replay records expose confidence as primary signal strength
    decisions = Counter(str(r.get("decision")) for r in records)
    regimes = Counter(_regime_norm(str(r.get("regime") or "")) for r in records)
    engines = Counter(_engine_norm(str(r.get("engine") or "")) for r in records)
    return {
        "probability_distribution": _dist(probs),
        "confidence_distribution": _dist(conf),
        "decision_distribution": dict(decisions),
        "regime_distribution": dict(regimes),
        "engine_distribution": dict(engines),
        "range_vs_trend": {
            "RANGE_bars": regimes.get("RANGE", 0),
            "TREND_bars": regimes.get("TREND", 0),
            "RANGE_pct": _safe_pct(regimes.get("RANGE", 0), len(records)),
            "TREND_pct": _safe_pct(regimes.get("TREND", 0), len(records)),
        },
    }


def build_engine_statistics(trades: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    trade_stats = build_engine_analysis(trades)
    bar_counts = Counter(_engine_norm(str(r.get("engine") or "")) for r in records)
    signal_counts = Counter(
        _engine_norm(str(r.get("engine") or ""))
        for r in records
        if str(r.get("decision")) in ("BUY", "SELL")
    )
    return {
        "trade_performance_by_engine": trade_stats,
        "bar_count_by_engine": dict(bar_counts),
        "actionable_signals_by_engine": dict(signal_counts),
    }


def build_regime_statistics(trades: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    trade_stats = build_regime_analysis(trades)
    bar_counts = Counter(_regime_norm(str(r.get("regime") or "")) for r in records)
    return {
        "trade_performance_by_regime": trade_stats,
        "bar_count_by_regime": dict(bar_counts),
    }


def build_journal_statistics(trades: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    journal = build_journal_integrity(trades)
    executed = sum(1 for r in records if r.get("execution_success"))
    attempted = sum(1 for r in records if str(r.get("decision")) in ("BUY", "SELL"))
    incomplete = max(0, attempted - len(trades))
    return {
        **journal,
        "completed_trades": len(trades),
        "incomplete_trades": incomplete,
        "executed_signals": executed,
        "entry_exit_reconstruction_success_rate_pct": journal.get(
            "replay_reconstruction_success_rate_pct"
        ),
        "lifecycle_integrity_pct": journal.get("journal_integrity_pct"),
    }


def build_pipeline_statistics(
    records: list[dict[str, Any]],
    replay_meta: dict[str, Any],
    hold_chain: dict[str, Any],
) -> dict[str, Any]:
    health = build_system_health(records, replay_meta)
    executed = sum(1 for r in records if r.get("execution_success"))
    actionable = sum(1 for r in records if str(r.get("decision")) in ("BUY", "SELL"))
    risk_rejected = sum(
        1 for r in records if str(r.get("decision")) in ("BUY", "SELL") and r.get("risk_allowed") is False
    )
    return {
        "healthgate_failures_estimate": int(
            (float(health.get("healthgate_fail_estimate_pct") or 0) / 100.0)
            * len(records)
        ),
        "healthgate_fail_rate_pct": health.get("healthgate_fail_estimate_pct"),
        "pipeline_timeout_rate_pct": health.get("timeout_rate_pct"),
        "pipeline_timeouts": health.get("pipeline_timeouts"),
        "exception_count": health.get("exception_count"),
        "execution_success_count": executed,
        "execution_success_rate_pct": _safe_pct(executed, actionable),
        "riskgate_rejection_rate_pct": _safe_pct(risk_rejected, actionable),
        "riskgate_holds": hold_chain.get("riskgate_hold", 0),
        "ml_signals_emitted": hold_chain.get("buy_emitted", 0) + hold_chain.get("sell_emitted", 0),
        "bars_evaluated": replay_meta.get("bars_evaluated", len(records)),
    }


def build_hold_funnel(records: list[dict[str, Any]], hold_chain: dict[str, Any]) -> dict[str, Any]:
    bars = len(records)
    ml_stages = hold_chain.get("ml_hold_stages") or {}
    orchestrator = bars - int(ml_stages.get("decision_hold", 0))
    calibration_pass = orchestrator - int(ml_stages.get("calibration_hold", 0))
    quality_pass = calibration_pass - int(ml_stages.get("trade_quality_hold", 0))
    filter_pass = quality_pass - int(ml_stages.get("rsi_filter_hold", 0)) - int(
        ml_stages.get("adx_filter_hold", 0)
    )
    ml_signals = int(hold_chain.get("buy_emitted", 0)) + int(hold_chain.get("sell_emitted", 0))
    risk_pass = ml_signals - int(hold_chain.get("riskgate_hold", 0))
    executed = sum(1 for r in records if r.get("execution_success"))

    funnel = [
        {"stage": "bars", "count": bars},
        {"stage": "ml_actionable", "count": orchestrator},
        {"stage": "trade_quality_pass", "count": quality_pass},
        {"stage": "profitability_pass", "count": filter_pass},
        {"stage": "risk_pass", "count": risk_pass},
        {"stage": "execution", "count": executed},
    ]

    holds = [r for r in records if str(r.get("decision")) == "HOLD"]
    hold_reasons = Counter(classify_hold(r) for r in holds)
    hold_analysis = build_hold_analysis(records, hold_chain)
    breakdown = hold_analysis.get("breakdown") or {}

    top_reasons = []
    for reason, count in hold_reasons.most_common(10):
        top_reasons.append(
            {
                "reason": reason,
                "count": count,
                "percentage": _safe_pct(count, len(holds)),
                "stage": reason.replace(" HOLD", "").lower(),
            }
        )
    for label, data in breakdown.items():
        if not any(t["reason"] == label for t in top_reasons):
            top_reasons.append(
                {
                    "reason": label,
                    "count": data.get("count", 0),
                    "percentage": data.get("pct", 0),
                    "stage": label.replace(" HOLD", "").lower(),
                    "source": data.get("source", "records"),
                }
            )
    top_reasons.sort(key=lambda x: x["count"], reverse=True)
    top_reasons = top_reasons[:10]

    return {
        "funnel": funnel,
        "hold_reasons": [
            {
                "reason": k,
                "count": v,
                "percentage": _safe_pct(v, len(holds)),
                "stage": k.replace(" HOLD", "").lower(),
            }
            for k, v in hold_reasons.most_common()
        ],
        "top_10_hold_reasons": top_reasons,
        "hold_chain": hold_chain,
    }


def build_cache_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    checksums = [str(r.get("feature_vector_checksum") or "") for r in records]
    unique_checksums = len({c for c in checksums if c})
    hits = sum(
        1
        for r in records
        if float((r.get("latency_ms") or {}).get("decision_ms") or 999) == 0.0
        and (r.get("latency_ms") or {}).get("decision_ms") is not None
    )
    misses = len(records) - hits
    conf_values = [round(float(r.get("confidence") or 0), 8) for r in records]
    unique_conf = len(set(conf_values))
    return {
        "cache_hit_estimate": hits,
        "cache_miss_estimate": misses,
        "cache_hit_ratio_pct": _safe_pct(hits, len(records)),
        "prediction_uniqueness_pct": _safe_pct(unique_checksums, len(records)),
        "unique_prediction_checksums": unique_checksums,
        "unique_confidence_values": unique_conf,
        "bars_evaluated": len(records),
        "phase27c_fix_expected": "unique keys per bar; checksum diversity >> 3",
        "phase27a_corrupted_baseline": {
            "unique_checksums": 3,
            "identical_confidence_bars": 5201,
        },
        "method": "decision_ms==0 indicates prediction cache hit; checksum diversity measures per-bar predictions",
    }


def determine_verdict(
    *,
    trades: list[dict[str, Any]],
    pipeline: dict[str, Any],
    journal: dict[str, Any],
    cache: dict[str, Any],
    hold_chain: dict[str, Any],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if float(pipeline.get("pipeline_timeout_rate_pct") or 0) >= 10:
        blockers.append("pipeline_timeout_rate >= 10%")
    if float(journal.get("journal_integrity_pct") or 0) < 100 and trades:
        blockers.append("journal_integrity < 100%")
    if float(cache.get("prediction_uniqueness_pct") or 0) < 50:
        blockers.append("prediction_uniqueness below 50% — possible cache regression")
    if len(trades) < 200:
        blockers.append(f"insufficient completed trades: {len(trades)} < 200")
    ml_out = int(hold_chain.get("buy_emitted", 0)) + int(hold_chain.get("sell_emitted", 0))
    if ml_out == 0:
        blockers.append("zero ML signals emitted after cache fix")
    if float(pipeline.get("healthgate_fail_rate_pct") or 0) > 5:
        blockers.append("healthgate failure rate > 5%")

    verdict = "READY_FOR_PAPER" if not blockers else "NOT_READY_FOR_PAPER"
    return verdict, blockers
