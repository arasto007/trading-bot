"""Phase 27G — 30-day trade performance validation metrics (read-only)."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _histogram, _mean, _median, _profit_factor
from tradingbot.ml.research.phase27a.metrics import (
    _engine_norm,
    _regime_norm,
    _safe_pct,
    build_profitability_metrics,
    build_trade_statistics,
)


MINIMUM_SAMPLE = 200
CONFIDENCE_BUCKETS = [
    ("0.50-0.60", 0.50, 0.60),
    ("0.60-0.70", 0.60, 0.70),
    ("0.70-0.80", 0.70, 0.80),
    ("0.80-0.90", 0.80, 0.90),
    ("0.90-1.00", 0.90, 1.01),
]


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)


def _session(hour: int) -> str:
    if 0 <= hour < 8:
        return "Asian"
    if 8 <= hour < 13:
        return "London"
    if 13 <= hour < 16:
        return "Overlap"
    if 16 <= hour < 21:
        return "New York"
    return "Asian"


def _subset_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "average_rr": 0.0,
            "realized_rr_avg": 0.0,
            "max_drawdown_pct": 0.0,
            "net_profit": 0.0,
        }
    pnls = [float(t["pnl"]) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    rr_vals = [float(t["rr"]) for t in trades if t.get("rr") is not None]
    pnl_r = [float(t["pnl_r"]) for t in trades if t.get("pnl_r") is not None]
    eq = _equity_curve(trades)
    dd_pct, _ = _max_drawdown(eq)
    return {
        "trade_count": len(trades),
        "win_rate_pct": _safe_pct(wins, len(trades)),
        "profit_factor": _profit_factor(trades),
        "expectancy": round(sum(pnls) / len(trades), 4),
        "average_rr": _mean(rr_vals),
        "realized_rr_avg": _mean(pnl_r),
        "max_drawdown_pct": round(dd_pct, 4),
        "net_profit": round(sum(pnls), 4),
    }


def build_trade_statistics_report(
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    replay_days: int,
) -> dict[str, Any]:
    base = build_trade_statistics(trades, records, replay_days=replay_days)
    win = sum(1 for t in trades if float(t["pnl"]) > 0)
    loss = sum(1 for t in trades if float(t["pnl"]) < 0)
    durations_sec = [float(t.get("duration_sec") or t["duration_bars"] * 300) for t in trades]
    sessions: Counter[str] = Counter()
    for t in trades:
        try:
            sessions[_session(_parse_ts(str(t["timestamp"])).hour)] += 1
        except Exception:
            sessions["unknown"] += 1
    return {
        "phase": "27G",
        "total_trades": len(trades),
        "buy_count": base.get("buy_trades", 0),
        "sell_count": base.get("sell_trades", 0),
        "win_trades": win,
        "loss_trades": loss,
        "win_rate_pct": base.get("win_rate"),
        "loss_rate_pct": base.get("loss_rate"),
        "average_trade_duration_bars": base.get("average_trade_duration_bars"),
        "median_trade_duration_bars": base.get("median_trade_duration_bars"),
        "average_trade_duration_sec": _mean(durations_sec),
        "median_trade_duration_sec": _median(durations_sec),
        "trades_per_day": base.get("trades_per_day"),
        "trades_per_session": dict(sessions),
        "bars_evaluated": base.get("bars_evaluated"),
    }


def build_profitability_report(trades: list[dict[str, Any]], *, initial: float = 10_000.0) -> dict[str, Any]:
    prof = build_profitability_metrics(trades, initial=initial)
    pnl_r = [float(t["pnl_r"]) for t in trades if t.get("pnl_r") is not None]
    return {
        "phase": "27G",
        "gross_profit": prof.get("gross_profit"),
        "gross_loss": prof.get("gross_loss"),
        "net_profit": prof.get("total_net_profit"),
        "profit_factor": prof.get("profit_factor"),
        "expectancy": prof.get("expectancy"),
        "average_win": prof.get("average_win"),
        "average_loss": prof.get("average_loss"),
        "largest_win": prof.get("largest_win"),
        "largest_loss": prof.get("largest_loss"),
        "average_rr": prof.get("average_rr"),
        "realized_rr_avg": _mean(pnl_r),
        "maximum_drawdown_pct": prof.get("max_drawdown_pct"),
        "maximum_drawdown_abs": prof.get("max_drawdown_abs"),
        "recovery_factor": prof.get("recovery_factor"),
        "sharpe_ratio": prof.get("sharpe_ratio"),
        "sortino_ratio": prof.get("sortino_ratio"),
        "calmar_ratio": prof.get("calmar_ratio"),
        "initial_balance": initial,
        "final_equity": prof.get("final_equity"),
    }


def build_direction_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"phase": "27G"}
    for side in ("BUY", "SELL"):
        subset = [t for t in trades if t["direction"] == side]
        out[side] = _subset_metrics(subset)
    return out


def build_regime_analysis_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    regimes = ["RANGE", "TREND", "TRANSITION"]
    stats: dict[str, Any] = {"phase": "27G"}
    for regime in regimes:
        subset = [t for t in trades if _regime_norm(t.get("regime", "")) == regime]
        stats[regime] = _subset_metrics(subset)

    ranked = sorted(
        ((r, stats[r]["expectancy"]) for r in regimes if stats[r]["trade_count"] > 0),
        key=lambda x: x[1],
        reverse=True,
    )
    stats["best_regime"] = ranked[0][0] if ranked else None
    stats["worst_regime"] = ranked[-1][0] if ranked else None
    return stats


def build_engine_analysis_report(
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    engines = ["phase9_9", "trend_rf_v41", "trend_rf_v40"]
    out: dict[str, Any] = {"phase": "27G"}

    for engine in engines:
        engine_trades = [t for t in trades if _engine_norm(t.get("engine", "")) == engine]
        engine_signals = [
            r
            for r in records
            if _engine_norm(str(r.get("engine") or "")) == engine
            and str(r.get("decision")) in ("BUY", "SELL")
        ]
        executions = [r for r in engine_signals if r.get("execution_success")]
        wins = sum(1 for t in engine_trades if float(t["pnl"]) > 0)
        losses = sum(1 for t in engine_trades if float(t["pnl"]) < 0)
        pnls = [float(t["pnl"]) for t in engine_trades]
        out[engine] = {
            "signals": len(engine_signals),
            "executions": len(executions),
            "completed_trades": len(engine_trades),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": _safe_pct(wins, len(engine_trades)),
            "profit_factor": _profit_factor(engine_trades),
            "expectancy": round(sum(pnls) / len(engine_trades), 4) if engine_trades else 0.0,
            "net_profit": round(sum(pnls), 4),
        }
    return out


def build_confidence_analysis_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in CONFIDENCE_BUCKETS}
    for t in trades:
        c = float(t.get("confidence") or 0.0)
        for label, lo, hi in CONFIDENCE_BUCKETS:
            if lo <= c < hi:
                buckets[label].append(t)
                break

    out: dict[str, Any] = {"phase": "27G", "buckets": {}}
    for label, _, _ in CONFIDENCE_BUCKETS:
        subset = buckets[label]
        pnls = [float(t["pnl"]) for t in subset]
        wins = sum(1 for p in pnls if p > 0)
        out["buckets"][label] = {
            "trade_count": len(subset),
            "win_rate_pct": _safe_pct(wins, len(subset)),
            "expectancy": round(sum(pnls) / len(subset), 4) if subset else 0.0,
            "profit_factor": _profit_factor(subset),
        }
    return out


def build_time_analysis_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_dow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_hour: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for t in trades:
        try:
            dt = _parse_ts(str(t["timestamp"]))
            by_session[_session(dt.hour)].append(t)
            by_dow[dt.strftime("%A")].append(t)
            by_hour[dt.hour].append(t)
        except Exception:
            continue

    def _session_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
        m = _subset_metrics(rows)
        return {
            "trade_count": m["trade_count"],
            "win_rate_pct": m["win_rate_pct"],
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "net_profit": m["net_profit"],
        }

    session_stats = {s: _session_stats(by_session.get(s, [])) for s in ("Asian", "London", "New York", "Overlap")}
    dow_stats = {d: _session_stats(rows) for d, rows in sorted(by_dow.items())}
    hour_stats = {str(h): _session_stats(rows) for h, rows in sorted(by_hour.items())}

    ranked_sessions = sorted(
        ((k, v["expectancy"]) for k, v in session_stats.items() if v["trade_count"] > 0),
        key=lambda x: x[1],
        reverse=True,
    )
    ranked_hours = sorted(
        ((k, v["expectancy"]) for k, v in hour_stats.items() if v["trade_count"] > 0),
        key=lambda x: x[1],
        reverse=True,
    )

    return {
        "phase": "27G",
        "sessions": session_stats,
        "day_of_week": dow_stats,
        "hour_of_day_utc": hour_stats,
        "best_session": ranked_sessions[0][0] if ranked_sessions else None,
        "worst_session": ranked_sessions[-1][0] if ranked_sessions else None,
        "best_hour_utc": ranked_hours[0][0] if ranked_hours else None,
        "worst_hour_utc": ranked_hours[-1][0] if ranked_hours else None,
    }


def build_risk_analysis_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
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
        "phase": "27G",
        "lot_sizing": {
            "mean": _mean(lots),
            "median": _median(lots),
            "min": round(min(lots), 4) if lots else 0.0,
            "max": round(max(lots), 4) if lots else 0.0,
            "distribution": _histogram(lots, bins=8),
        },
        "risk_percent": {
            "mean": _mean(risks),
            "median": _median(risks),
            "max": round(max(risks), 4) if risks else None,
        },
        "sl_distance": {"mean": _mean(sl_dist), "median": _median(sl_dist), "distribution": _histogram(sl_dist, bins=8)},
        "tp_distance": {"mean": _mean(tp_dist), "median": _median(tp_dist), "distribution": _histogram(tp_dist, bins=8)},
        "rr_consistency": {
            "target_rr": 2.0,
            "average_planned_rr": _mean(rr_vals),
            "rr_std_dev": round(statistics.stdev(rr_vals), 4) if len(rr_vals) > 1 else 0.0,
            "distribution": _histogram(rr_vals, bins=8),
        },
        "mae": {"mean": _mean(mae), "median": _median(mae), "max": round(max(mae), 4) if mae else 0.0},
        "mfe": {"mean": _mean(mfe), "median": _median(mfe), "max": round(max(mfe), 4) if mfe else 0.0},
        "mae_mfe_ratio": round(_mean(mae) / _mean(mfe), 4) if _mean(mfe) else None,
    }


def build_exit_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = Counter(str(t.get("exit_reason") or "unknown").lower() for t in trades)
    total = len(trades) or 1
    breakdown = {
        k.upper(): {"count": v, "pct": _safe_pct(v, total)} for k, v in sorted(reasons.items())
    }
    sl = reasons.get("sl", 0)
    tp = reasons.get("tp", 0)
    timeout = reasons.get("timeout", 0)
    return {
        "phase": "27G",
        "total_trades": len(trades),
        "exit_reasons": breakdown,
        "sl_count": sl,
        "tp_count": tp,
        "timeout_count": timeout,
        "sl_pct": _safe_pct(sl, total),
        "tp_pct": _safe_pct(tp, total),
        "timeout_pct": _safe_pct(timeout, total),
    }


def build_signal_funnel(records: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    bars = len(records)
    ml_signals = sum(1 for r in records if str(r.get("decision")) in ("BUY", "SELL"))
    risk_approved = sum(
        1 for r in records if str(r.get("decision")) in ("BUY", "SELL") and r.get("risk_allowed") is True
    )
    executed = sum(1 for r in records if r.get("execution_success") is True)
    winning = sum(1 for t in trades if float(t["pnl"]) > 0)
    losing = sum(1 for t in trades if float(t["pnl"]) < 0)

    stages = [
        ("bars", bars),
        ("ml_signals", ml_signals),
        ("risk_approved", risk_approved),
        ("executed_trades", executed),
        ("winning_trades", winning),
        ("losing_trades", losing),
    ]
    funnel = []
    prev = bars
    for name, count in stages:
        funnel.append(
            {
                "stage": name,
                "count": count,
                "pct_of_bars": _safe_pct(count, bars),
                "loss_from_previous": prev - count if name != "bars" else 0,
            }
        )
        prev = count
    return {"phase": "27G", "funnel": funnel}


def build_equity_curve_report(trades: list[dict[str, Any]], *, initial: float = 10_000.0) -> dict[str, Any]:
    points = _equity_curve(trades, initial=initial)
    return {"phase": "27G", "initial_balance": initial, "points": points, "final_equity": points[-1]["equity"] if points else initial}


def build_drawdown_curve_report(trades: list[dict[str, Any]], *, initial: float = 10_000.0) -> dict[str, Any]:
    points = _equity_curve(trades, initial=initial)
    dd_points: list[dict[str, Any]] = []
    peak = -1e18
    max_dd = 0.0
    for pt in points:
        e = float(pt["equity"])
        peak = max(peak, e)
        dd = (peak - e) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        dd_points.append({"timestamp": pt["timestamp"], "drawdown_pct": round(dd, 4), "equity": e})
    return {"phase": "27G", "max_drawdown_pct": round(max_dd, 4), "points": dd_points}


def determine_verdict(
    *,
    trades: list[dict[str, Any]],
    trade_stats: dict[str, Any],
    profitability: dict[str, Any],
    exit_analysis: dict[str, Any],
) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    evidence: list[str] = []

    n = len(trades)
    if n < MINIMUM_SAMPLE:
        blockers.append(f"completed_trades {n} < minimum {MINIMUM_SAMPLE}")
    else:
        evidence.append(f"sample_size {n} >= {MINIMUM_SAMPLE}")

    if trade_stats.get("total_trades") != n:
        blockers.append("trade_statistics count mismatch")
    else:
        evidence.append("trade_statistics reconciled")

    required_exit = exit_analysis.get("sl_count", 0) + exit_analysis.get("tp_count", 0) + exit_analysis.get("timeout_count", 0)
    if required_exit != n:
        blockers.append("exit_analysis does not cover all trades")
    else:
        evidence.append("exit_reasons fully classified")

    pf = profitability.get("profit_factor")
    evidence.append(f"profit_factor={pf} expectancy={profitability.get('expectancy')}")
    evidence.append(f"win_rate={trade_stats.get('win_rate_pct')}% max_dd={profitability.get('maximum_drawdown_pct')}%")

    if blockers:
        return "PERFORMANCE_NOT_VALIDATED", blockers, evidence
    return "PERFORMANCE_VALIDATED", blockers, evidence


def build_final_report(
    *,
    trades: list[dict[str, Any]],
    records: list[dict[str, Any]],
    replay_meta: dict[str, Any],
    trade_stats: dict[str, Any],
    profitability: dict[str, Any],
    direction: dict[str, Any],
    regime: dict[str, Any],
    engine: dict[str, Any],
    funnel: dict[str, Any],
    exit_analysis: dict[str, Any],
    replay_days: int,
) -> dict[str, Any]:
    verdict, blockers, evidence = determine_verdict(
        trades=trades,
        trade_stats=trade_stats,
        profitability=profitability,
        exit_analysis=exit_analysis,
    )
    return {
        "phase": "27G",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "input_source": "phase27f_repaired_replay",
        "replay_days": replay_days,
        "bars_evaluated": replay_meta.get("bars_evaluated", len(records)),
        "completed_trades": len(trades),
        "minimum_sample": MINIMUM_SAMPLE,
        "sample_sufficient": len(trades) >= MINIMUM_SAMPLE,
        "blockers": blockers,
        "evidence": evidence,
        "profit_factor": profitability.get("profit_factor"),
        "expectancy": profitability.get("expectancy"),
        "net_profit": profitability.get("net_profit"),
        "win_rate_pct": trade_stats.get("win_rate_pct"),
        "max_drawdown_pct": profitability.get("maximum_drawdown_pct"),
        "best_regime": regime.get("best_regime"),
        "worst_regime": regime.get("worst_regime"),
        "signal_funnel_summary": funnel.get("funnel"),
        "conclusion": (
            f"30-day post-27F replay: {len(trades)} completed trades analyzed. "
            f"PF={profitability.get('profit_factor')} expectancy={profitability.get('expectancy')} "
            f"win_rate={trade_stats.get('win_rate_pct')}%. Verdict: {verdict}."
        ),
    }
