"""Phase 27A metrics — profitability, regime, engine, risk, decision, health."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any

from tradingbot.backtest.metrics import _BARS_PER_YEAR, _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import (
    _equity_curve,
    _histogram,
    _mean,
    _median,
    _profit_factor,
    _streaks,
)


def _calmar(return_pct: float, max_dd_pct: float) -> float:
    if max_dd_pct <= 0:
        return float("inf") if return_pct > 0 else 0.0
    return round(return_pct / max_dd_pct, 4)


def _safe_pct(num: float, den: float) -> float:
    return round(100.0 * num / den, 2) if den else 0.0


def _regime_norm(regime: str) -> str:
    r = str(regime or "").upper()
    if r in ("RANGE", "RANGING"):
        return "RANGE"
    if r == "TREND":
        return "TREND"
    if r in ("TRANSITION", "HIGH_VOLATILITY"):
        return r
    if r == "NO_TRADE":
        return "NO_TRADE"
    return "OTHER"


def _engine_norm(engine: str) -> str:
    e = str(engine or "").lower()
    if "phase9" in e or "phase99" in e or e == "phase9_9":
        return "phase9_9"
    if "v41" in e or "trend_rf_v41" in e:
        return "trend_rf_v41"
    if "v40" in e or "trend_rf_v40" in e:
        return "trend_rf_v40"
    if "trend" in e:
        return "trend_rf_v41"
    return "other"


def build_profitability_metrics(trades: list[dict[str, Any]], *, initial: float = 10_000.0) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net = sum(pnls)
    eq = _equity_curve(trades, initial=initial)
    eq_vals = [p["equity"] for p in eq]
    max_dd_pct, max_dd_abs = _max_drawdown(eq)
    ret_pct = (net / initial * 100) if initial else 0.0
    rr_vals = [float(t["rr"]) for t in trades if t.get("rr") is not None]
    pf = _profit_factor(trades)

    return {
        "total_net_profit": round(net, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "profit_factor": pf,
        "expectancy": round(net / len(trades), 4) if trades else 0.0,
        "average_trade": _mean(pnls),
        "median_trade": _median(pnls),
        "average_rr": _mean(rr_vals),
        "average_win": round(sum(wins) / len(wins), 4) if wins else 0.0,
        "average_loss": round(-sum(losses) / len(losses), 4) if losses else 0.0,
        "largest_win": round(max(wins), 4) if wins else 0.0,
        "largest_loss": round(min(losses), 4) if losses else 0.0,
        "max_consecutive_wins": _streaks(trades)["longest_winning_streak"],
        "max_consecutive_losses": _streaks(trades)["longest_losing_streak"],
        "sharpe_ratio": round(_sharpe(eq, "M5"), 4),
        "sortino_ratio": _sortino(eq, "M5"),
        "calmar_ratio": _calmar(ret_pct, max_dd_pct),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "max_drawdown_abs": round(max_dd_abs, 4),
        "recovery_factor": _recovery_factor(net, max_dd_abs),
        "return_drawdown_ratio": _calmar(ret_pct, max_dd_pct),
        "initial_balance": initial,
        "final_equity": round(eq_vals[-1], 4) if eq_vals else initial,
    }


def build_trade_statistics(
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    replay_days: int,
) -> dict[str, Any]:
    holds = sum(1 for r in records if str(r.get("decision")) == "HOLD")
    buys = sum(1 for t in trades if t["direction"] == "BUY")
    sells = sum(1 for t in trades if t["direction"] == "SELL")
    total_decisions = len(records)
    win = sum(1 for t in trades if float(t["pnl"]) > 0)
    loss = sum(1 for t in trades if float(t["pnl"]) < 0)
    be = sum(1 for t in trades if float(t["pnl"]) == 0)
    durations = [int(t["duration_bars"]) for t in trades]

    return {
        "total_trades": len(trades),
        "buy_trades": buys,
        "sell_trades": sells,
        "hold_decisions": holds,
        "buy_pct": _safe_pct(buys, len(trades)),
        "sell_pct": _safe_pct(sells, len(trades)),
        "hold_pct": _safe_pct(holds, total_decisions),
        "win_rate": _safe_pct(win, len(trades)),
        "loss_rate": _safe_pct(loss, len(trades)),
        "breakeven_rate": _safe_pct(be, len(trades)),
        "trades_per_day": round(len(trades) / max(replay_days, 1), 4),
        "average_trades_per_session": round(len(trades) / max(replay_days * 3, 1), 4),
        "average_trade_duration_bars": _mean([float(d) for d in durations]),
        "median_trade_duration_bars": _median([float(d) for d in durations]),
        "maximum_duration_bars": max(durations) if durations else 0,
        "minimum_duration_bars": min(durations) if durations else 0,
        "bars_evaluated": total_decisions,
    }


def build_buy_sell_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for side in ("BUY", "SELL"):
        subset = [t for t in trades if t["direction"] == side]
        pnls = [float(t["pnl"]) for t in subset]
        out[side] = {
            "count": len(subset),
            "win_rate": _safe_pct(sum(1 for p in pnls if p > 0), len(subset)),
            "profit_factor": _profit_factor(subset),
            "net_profit": round(sum(pnls), 4),
            "expectancy": round(sum(pnls) / len(subset), 4) if subset else 0.0,
            "average_confidence": _mean([float(t["confidence"]) for t in subset]),
        }
    return out


def _bucket_stats(trades: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    total_pnl = sum(float(t["pnl"]) for t in trades) or 1e-9
    out: dict[str, Any] = {}
    for name, subset in sorted(groups.items()):
        pnls = [float(t["pnl"]) for t in subset]
        out[name] = {
            "trade_count": len(subset),
            "win_rate": _safe_pct(sum(1 for p in pnls if p > 0), len(subset)),
            "profit_factor": _profit_factor(subset),
            "expectancy": round(sum(pnls) / len(subset), 4) if subset else 0.0,
            "net_profit": round(sum(pnls), 4),
            "average_confidence": _mean([float(t["confidence"]) for t in subset]),
            "average_probability": _mean([float(t.get("probability") or t["confidence"]) for t in subset]),
            "average_rr": _mean([float(t["rr"]) for t in subset if t.get("rr") is not None]),
            "average_duration_bars": _mean([float(t["duration_bars"]) for t in subset]),
            "contribution_to_total_pnl_pct": round(100.0 * sum(pnls) / total_pnl, 2),
        }
    return out


def build_regime_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    regimes = ["RANGE", "TREND", "TRANSITION", "HIGH_VOLATILITY", "NO_TRADE", "OTHER"]
    stats = _bucket_stats(trades, lambda t: _regime_norm(t.get("regime", "")))
    return {r: stats.get(r, {"trade_count": 0}) for r in regimes} | stats


def build_engine_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    engines = ["phase9_9", "trend_rf_v40", "trend_rf_v41", "other"]
    stats = _bucket_stats(trades, lambda t: _engine_norm(t.get("engine", "")))
    return {e: stats.get(e, {"trade_count": 0}) for e in engines}


def build_risk_analysis(trades: list[dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    rejected = [
        r for r in records
        if str(r.get("decision")) in ("BUY", "SELL") and r.get("risk_allowed") is False
    ]
    blocked_exec = [
        r for r in records
        if str(r.get("decision")) in ("BUY", "SELL") and r.get("execution_success") is False
    ]
    lots = [float(t["lot"]) for t in trades]
    risks = [float(t["risk_percent"]) for t in trades if t.get("risk_percent") is not None]
    sl_dist = [
        abs(float(t["entry_price"]) - float(t["sl"]))
        for t in trades
        if t.get("sl") is not None and t.get("entry_price")
    ]
    tp_dist = [
        abs(float(t["tp"]) - float(t["entry_price"]))
        for t in trades
        if t.get("tp") is not None and t.get("entry_price")
    ]
    rr_vals = [float(t["rr"]) for t in trades if t.get("rr") is not None]
    mae = [float(t["mae"]) for t in trades]
    mfe = [float(t["mfe"]) for t in trades]

    return {
        "riskgate_rejected_signals": len(rejected),
        "blocked_executions": len(blocked_exec),
        "rejection_reasons": dict(Counter(str(r.get("risk_reason") or "unknown") for r in rejected)),
        "lot_size_distribution": _histogram(lots, bins=8),
        "average_risk_percent": _mean(risks),
        "maximum_risk_percent": round(max(risks), 4) if risks else None,
        "sl_distance_avg": _mean(sl_dist),
        "tp_distance_avg": _mean(tp_dist),
        "rr_distribution": _histogram(rr_vals, bins=8),
        "mae_avg": _mean(mae),
        "mfe_avg": _mean(mfe),
        "mae_mfe_ratio": round(_mean(mae) / _mean(mfe), 4) if _mean(mfe) else None,
        "killswitch_activity": 0,
        "emergency_stop_activity": 0,
    }


def classify_hold(record: dict[str, Any]) -> str:
    if str(record.get("decision")) != "HOLD":
        return ""
    errors = [str(e).lower() for e in (record.get("pipeline_errors") or [])]
    err_join = " ".join(errors)
    if "pipeline_timeout" in err_join or "timeout" in err_join:
        return "Timeout HOLD"
    if record.get("registry_source") == "safe_hold" or "health" in err_join or "fallback" in err_join:
        return "HealthGate HOLD"
    regime = str(record.get("regime") or "").upper()
    if regime == "NO_TRADE":
        return "No Trade Regime HOLD"
    if record.get("risk_allowed") is False:
        return "Risk HOLD"
    filt = record.get("filter_diagnostics") or {}
    blocked = filt.get("blocked_by") or []
    if isinstance(blocked, list):
        if "rsi_filter" in blocked:
            return "RSI Filter HOLD"
        if "adx_filter" in blocked:
            return "ADX Filter HOLD"
    if filt.get("passed") is False:
        return "RSI Filter HOLD"
    conf = float(record.get("confidence") or 0.0)
    if conf < 0.01 and regime not in ("NO_TRADE",):
        return "Calibration HOLD"
    if float(record.get("quality_score") or 0.0) < 0.01:
        return "Quality HOLD"
    return "Unknown HOLD"


def build_hold_analysis(records: list[dict[str, Any]], hold_chain: dict[str, Any] | None = None) -> dict[str, Any]:
    holds = [r for r in records if str(r.get("decision")) == "HOLD"]
    reasons = Counter(classify_hold(r) for r in holds)
    total = len(holds) or 1
    breakdown = {k: {"count": v, "pct": _safe_pct(v, total)} for k, v in reasons.items() if k}

    if hold_chain:
        ml_stages = hold_chain.get("ml_hold_stages") or {}
        stage_map = {
            "decision_hold": "Decision HOLD",
            "calibration_hold": "Calibration HOLD",
            "trade_quality_hold": "Quality HOLD",
            "rsi_filter_hold": "RSI Filter HOLD",
            "adx_filter_hold": "ADX Filter HOLD",
        }
        for key, label in stage_map.items():
            count = int(ml_stages.get(key, 0))
            if count:
                breakdown[label] = {"count": count, "pct": _safe_pct(count, total), "source": "hold_chain"}
        rg = int(hold_chain.get("riskgate_hold", 0))
        if rg:
            breakdown["RiskGate HOLD"] = {"count": rg, "pct": _safe_pct(rg, total), "source": "hold_chain"}

    return {
        "total_holds": len(holds),
        "breakdown": breakdown,
        "hold_chain_snapshot": hold_chain or {},
    }


def build_decision_analysis(records: list[dict[str, Any]], hold_chain: dict[str, Any]) -> dict[str, Any]:
    decisions = Counter(str(r.get("decision")) for r in records)
    return {
        "decision_counts": dict(decisions),
        "executed_count": sum(1 for r in records if r.get("execution_success")),
        "ml_hold_chain": hold_chain.get("ml_hold_stages", {}),
        "riskgate_holds": hold_chain.get("riskgate_hold", 0),
        "riskgate_block_reasons": hold_chain.get("riskgate_block_reasons", {}),
    }


def build_latency_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    totals = [
        float((r.get("latency_ms") or {}).get("total_ms", 0))
        for r in records
        if r.get("latency_ms")
    ]
    if not totals:
        return {"count": 0}
    totals_sorted = sorted(totals)

    def pct(p: float) -> float:
        if not totals_sorted:
            return 0.0
        idx = min(len(totals_sorted) - 1, int(p * len(totals_sorted)))
        return round(totals_sorted[idx], 3)

    over_500 = sum(1 for t in totals if t > 500)
    return {
        "count": len(totals),
        "average_ms": _mean(totals),
        "median_ms": _median(totals),
        "p95_ms": pct(0.95),
        "p99_ms": pct(0.99),
        "over_500ms_count": over_500,
        "timeout_rate_pct": _safe_pct(over_500, len(totals)),
    }


def build_cache_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristic: sub-20ms total latency suggests prediction cache hit."""
    hits = misses = 0
    for r in records:
        lat = r.get("latency_ms") or {}
        total = float(lat.get("total_ms", 999))
        if total <= 20 and lat:
            hits += 1
        elif lat:
            misses += 1
    total = hits + misses or 1
    return {
        "cache_hit_estimate": hits,
        "cache_miss_estimate": misses,
        "cache_hit_pct": _safe_pct(hits, total),
        "cache_miss_pct": _safe_pct(misses, total),
        "method": "heuristic total_ms<=20ms",
    }


def build_system_health(records: list[dict[str, Any]], replay_meta: dict[str, Any]) -> dict[str, Any]:
    lat = build_latency_analysis(records)
    errors = sum(len(r.get("pipeline_errors") or []) for r in records)
    fallbacks = sum(1 for r in records if r.get("registry_source") == "safe_hold")
    health_fails = fallbacks + sum(
        1 for r in records
        if any("health" in str(e).lower() for e in (r.get("pipeline_errors") or []))
    )
    bars = int(replay_meta.get("bars_evaluated") or len(records) or 1)
    return {
        "healthgate_pass_estimate_pct": _safe_pct(bars - health_fails, bars),
        "healthgate_fail_estimate_pct": _safe_pct(health_fails, bars),
        "pipeline_timeouts": lat.get("over_500ms_count", 0),
        "timeout_rate_pct": lat.get("timeout_rate_pct", 0),
        "exception_count": errors,
        "fallback_count": fallbacks,
        "legacy_fallback_count": 0,
        "average_decision_latency_ms": lat.get("average_ms"),
        "median_decision_latency_ms": lat.get("median_ms"),
        "p95_latency_ms": lat.get("p95_ms"),
        "p99_latency_ms": lat.get("p99_ms"),
    }


def build_journal_integrity(trades: list[dict[str, Any]]) -> dict[str, Any]:
    required = (
        "entry_price", "fill_price", "exit_price", "sl", "tp", "lot",
        "timestamp", "exit_timestamp", "pnl", "exit_reason",
    )
    complete = 0
    missing_fields: Counter[str] = Counter()
    for t in trades:
        ok = True
        for f in required:
            val = t.get(f)
            if val is None or (isinstance(val, (int, float)) and f.endswith("price") and float(val) <= 0):
                missing_fields[f] += 1
                ok = False
        if ok:
            complete += 1
    dup_ts = len(trades) - len({t["timestamp"] for t in trades})
    return {
        "total_trades": len(trades),
        "complete_trades": complete,
        "journal_integrity_pct": _safe_pct(complete, len(trades)),
        "missing_field_counts": dict(missing_fields),
        "duplicate_timestamps": dup_ts,
        "orphan_trades": 0,
        "replay_reconstruction_success_rate_pct": _safe_pct(complete, len(trades)),
    }


def build_integrity_scores(
    *,
    trades: list[dict[str, Any]],
    journal: dict[str, Any],
    health: dict[str, Any],
    profitability: dict[str, Any],
    prior_phases: dict[str, Any],
) -> dict[str, Any]:
    n = len(trades)
    timeout_pct = float(health.get("timeout_rate_pct") or 0)
    journal_pct = float(journal.get("journal_integrity_pct") or 0)

    scores = {
        "Architecture": min(100, 85 + (5 if prior_phases.get("phase25b") == "PARITY_RESTORED" else 0)),
        "Reliability": max(0, 100 - int(timeout_pct * 2) - (20 if timeout_pct > 10 else 0)),
        "Execution": journal_pct,
        "Risk": 78 if n >= 50 else 55,
        "Performance": min(100, max(30, 50 + int(float(profitability.get("profit_factor") or 0) * 10))),
        "Consistency": 80 if n >= 100 else 50,
        "Journal": journal_pct,
        "Paper_Readiness": 0,
    }
    sample_penalty = 0 if n >= 200 else max(0, 200 - n) // 2
    scores["Paper_Readiness"] = max(
        0,
        int(
            scores["Architecture"] * 0.15
            + scores["Reliability"] * 0.20
            + scores["Execution"] * 0.15
            + scores["Risk"] * 0.15
            + scores["Journal"] * 0.15
            + scores["Consistency"] * 0.10
            + min(100, n) * 0.10
            - sample_penalty
        ),
    )
    overall = round(sum(scores.values()) / len(scores), 1)
    return {"scores": scores, "overall_score": overall, "sample_size": n, "minimum_sample": 200}


def build_paper_readiness(
    *,
    scores: dict[str, Any],
    trades: list[dict[str, Any]],
    health: dict[str, Any],
    journal: dict[str, Any],
    prior: dict[str, Any],
) -> dict[str, Any]:
    n = len(trades)
    checks = {
        "production_pipeline_25b": prior.get("phase25b") == "PARITY_RESTORED",
        "startup_safe_26d": prior.get("phase26d") == "STARTUP_SAFE",
        "journal_repair_26c": prior.get("phase26c") == "JOURNAL_READY",
        "minimum_200_trades": n >= 200,
        "journal_integrity_100": journal.get("journal_integrity_pct", 0) >= 100,
        "timeout_rate_under_10pct": float(health.get("timeout_rate_pct") or 0) < 10,
        "positive_expectancy": float((trades and sum(float(t["pnl"]) for t in trades) / n) or 0) > 0,
    }
    blockers = [k for k, v in checks.items() if not v]
    ready = len(blockers) == 0
    return {
        "checks": checks,
        "blockers": blockers,
        "trade_count": n,
        "paper_readiness_score": scores.get("scores", {}).get("Paper_Readiness"),
        "ready": ready,
        "note": "Verdict uses infrastructure + statistical + health criteria — not profit alone.",
    }
