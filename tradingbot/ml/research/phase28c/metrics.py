"""Phase 28C — performance metrics, daily stats, backtest comparison."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from tradingbot.backtest.metrics import _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.analyzers import _equity_curve, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _safe_pct

INITIAL_BALANCE = 10_000.0
DEVIATION_THRESHOLD_PCT = 20.0


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _pf_val(pf: Any) -> float:
    if isinstance(pf, (int, float)):
        return float(pf)
    return 0.0


def _pct_deviation(actual: float, expected: float) -> float:
    if expected == 0:
        return 0.0 if actual == 0 else 100.0
    return round(abs(actual - expected) / abs(expected) * 100, 4)


def build_performance_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"phase": "28C", "completed_trades": 0}

    pseudo = [
        {
            "pnl": float(t.get("pnl") or 0),
            "pnl_r": float(t.get("pnl_r") or 0),
            "direction": t.get("direction"),
            "timestamp": t.get("time_open"),
            "exit_timestamp": t.get("time_close"),
            "duration_bars": t.get("duration_bars"),
        }
        for t in trades
    ]
    pnls = [float(t["pnl"]) for t in pseudo]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    net = sum(pnls)
    eq = _equity_curve(pseudo, initial=INITIAL_BALANCE)
    dd_pct, dd_abs = _max_drawdown(eq)
    ret_pct = net / INITIAL_BALANCE * 100
    rs = [float(t["pnl_r"]) for t in pseudo]
    durs = [float(t["duration_bars"]) for t in pseudo if t.get("duration_bars") is not None]

    reasons: dict[str, int] = defaultdict(int)
    for t in trades:
        r = str(t.get("exit_reason") or "unknown").lower()
        if r in ("hybrid_time", "time", "timeout"):
            reasons["partial_plus_timeout" if "hybrid" in r else "timeout_only"] += 1
        elif r in ("hybrid_sl", "sl"):
            reasons["partial_plus_sl" if "hybrid" in r else "sl"] += 1
        elif r == "tp":
            reasons["tp"] += 1
        else:
            reasons[r] += 1

    return {
        "phase": "28C",
        "completed_trades": len(trades),
        "buy_count": sum(1 for t in pseudo if t.get("direction") == "BUY"),
        "sell_count": sum(1 for t in pseudo if t.get("direction") == "SELL"),
        "win_rate_pct": _safe_pct(len(wins), len(pseudo)),
        "profit_factor": _profit_factor(pseudo),
        "expectancy": round(net / len(pseudo), 4),
        "net_profit": round(net, 4),
        "average_r": _mean(rs),
        "max_drawdown_pct": round(dd_pct, 4),
        "sharpe_ratio": round(_sharpe(eq, "M5"), 4),
        "sortino_ratio": round(_sortino(eq, "M5"), 4),
        "calmar_ratio": round(ret_pct / dd_pct, 4) if dd_pct > 0 else 0.0,
        "recovery_factor": _recovery_factor(net, dd_abs),
        "average_trade_duration_bars": _mean(durs),
        "average_mae_r": _mean([float(t.get("mae") or 0) for t in trades]),
        "average_mfe_r": _mean([float(t.get("mfe") or 0) for t in trades]),
        "exit_reason_distribution": dict(reasons),
    }


def build_execution_quality(trades: list[dict[str, Any]], executions: list[dict[str, Any]]) -> dict[str, Any]:
    spreads = [float(t.get("spread") or 0) for t in trades if t.get("spread")]
    slippages = [float(e.get("slippage_pips") or 0) for e in executions if e.get("slippage_pips") is not None]
    fill_gaps = []
    for t in trades:
        entry = float(t.get("entry_price") or 0)
        fill = float(t.get("fill_price") or 0)
        if entry > 0 and fill > 0:
            fill_gaps.append(abs(fill - entry))
    return {
        "phase": "28C",
        "trade_count": len(trades),
        "execution_count": len(executions),
        "mean_spread": _mean(spreads),
        "mean_slippage_pips": _mean(slippages),
        "mean_fill_gap": _mean(fill_gaps),
        "mean_commission": _mean([float(t.get("commission") or 0) for t in trades]),
        "mean_swap": _mean([float(t.get("swap") or 0) for t in trades]),
        "mean_duration_bars": _mean([float(t.get("duration_bars") or 0) for t in trades]),
    }


def build_daily_statistics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        ts = str(t.get("time_close") or t.get("time_open") or "")[:10]
        if ts:
            by_day[ts].append(float(t.get("pnl") or 0))

    days = []
    for day in sorted(by_day.keys()):
        pnls = by_day[day]
        days.append(
            {
                "date": day,
                "trades": len(pnls),
                "net_pnl": round(sum(pnls), 4),
                "win_rate_pct": _safe_pct(sum(1 for p in pnls if p > 0), len(pnls)),
            }
        )
    return {"phase": "28C", "days": days, "day_count": len(days)}


def load_backtest_baseline() -> dict[str, Any]:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    p28a = root / "phase28a" / "strategy_a_results.json"
    p28b = root / "phase28b" / "performance_validation.json"
    baseline: dict[str, Any] = {"source": "phase28a_aggregate"}
    if p28a.is_file():
        import json

        data = json.loads(p28a.read_text(encoding="utf-8"))
        agg = data.get("aggregate") or {}
        w30 = (data.get("windows") or {}).get("30") or {}
        baseline = {
            "source": "phase28a",
            "aggregate": {
                "profit_factor": _pf_val(agg.get("profit_factor")),
                "expectancy": float(agg.get("expectancy") or 0),
                "win_rate_pct": float(agg.get("win_rate_pct") or 0),
                "max_drawdown_pct": float(agg.get("max_drawdown_pct") or 0),
                "completed_trades": int(agg.get("completed_trades") or 0),
            },
            "window_30d": {
                "profit_factor": _pf_val(w30.get("profit_factor")),
                "expectancy": float(w30.get("expectancy") or 0),
                "win_rate_pct": float(w30.get("win_rate_pct") or 0),
                "max_drawdown_pct": float(w30.get("max_drawdown_pct") or 0),
                "completed_trades": int(w30.get("completed_trades") or 0),
            },
        }
    if p28b.is_file():
        import json

        pb = json.loads(p28b.read_text(encoding="utf-8"))
        baseline["phase28b_production"] = pb.get("production_hybrid_b")
    return baseline


def build_backtest_vs_live(
    live: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    ref = baseline.get("window_30d") or baseline.get("aggregate") or {}
    if not live.get("completed_trades"):
        return {
            "phase": "28C",
            "comparison_available": False,
            "reason": "no_live_trades",
            "threshold_pct": DEVIATION_THRESHOLD_PCT,
        }
    metrics = {
        "profit_factor": (_pf_val(live.get("profit_factor")), float(ref.get("profit_factor") or 0)),
        "expectancy": (float(live.get("expectancy") or 0), float(ref.get("expectancy") or 0)),
        "win_rate_pct": (float(live.get("win_rate_pct") or 0), float(ref.get("win_rate_pct") or 0)),
        "max_drawdown_pct": (float(live.get("max_drawdown_pct") or 0), float(ref.get("max_drawdown_pct") or 0)),
    }
    deviations: dict[str, Any] = {}
    over_threshold: list[str] = []
    for name, (actual, expected) in metrics.items():
        dev = _pct_deviation(actual, expected)
        deviations[name] = {"live": actual, "backtest": expected, "deviation_pct": dev}
        if dev > DEVIATION_THRESHOLD_PCT:
            over_threshold.append(name)
    trade_freq_dev = _pct_deviation(
        float(live.get("completed_trades") or 0),
        float(ref.get("completed_trades") or 1),
    )
    return {
        "phase": "28C",
        "comparison_available": True,
        "baseline_source": baseline.get("source"),
        "deviations": deviations,
        "trade_frequency_deviation_pct": trade_freq_dev,
        "metrics_over_20pct": over_threshold,
        "within_acceptable_range": len(over_threshold) == 0 and trade_freq_dev <= DEVIATION_THRESHOLD_PCT,
        "threshold_pct": DEVIATION_THRESHOLD_PCT,
    }


def determine_verdict(
    *,
    trade_count: int,
    period_days: float,
    failure_monitoring: dict[str, Any],
    backtest_vs_live: dict[str, Any],
    hybrid_validations: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if trade_count < 200:
        blockers.append(f"insufficient trades: {trade_count} < 200")
        return "INSUFFICIENT_SAMPLE", blockers
    if period_days < 14:
        blockers.append(f"insufficient period: {period_days}d < 14d")

    if failure_monitoring.get("failure_count", 0) > 0:
        blockers.append("failure monitoring detected issues")
    if hybrid_validations and not all(h.get("hybrid_valid") for h in hybrid_validations):
        invalid = sum(1 for h in hybrid_validations if not h.get("hybrid_valid"))
        blockers.append(f"{invalid} hybrid exit validation failures")

    if backtest_vs_live.get("comparison_available") and not backtest_vs_live.get("within_acceptable_range"):
        blockers.append("backtest vs live deviation exceeds 20%")

    if blockers and trade_count >= 200:
        return "HYBRID_B_NEEDS_INVESTIGATION", blockers
    if trade_count >= 200 and not blockers:
        return "HYBRID_B_VALIDATED_FOR_LIVE", blockers
    return "INSUFFICIENT_SAMPLE", blockers
