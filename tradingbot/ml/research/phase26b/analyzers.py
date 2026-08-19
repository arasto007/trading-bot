"""Statistical analyzers for Phase 26B paper trading validation."""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from tradingbot.backtest.metrics import _BARS_PER_YEAR, _max_drawdown, _sharpe
from tradingbot.ml.research.phase22e.metrics import _recovery_factor, _sortino
from tradingbot.ml.research.phase26b.data_loader import MINIMUM_SAMPLE_SIZE


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 4) if values else 0.0


def _histogram(values: list[float], *, bins: int = 10) -> list[dict[str, Any]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [{"bin_start": lo, "bin_end": hi, "count": len(values)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(bins - 1, int((v - lo) / width))
        counts[idx] += 1
    return [
        {"bin_start": round(lo + i * width, 6), "bin_end": round(lo + (i + 1) * width, 6), "count": c}
        for i, c in enumerate(counts)
    ]


def _profit_factor(trades: list[dict[str, Any]]) -> float | str:
    wins = sum(float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) > 0)
    losses = abs(sum(float(t.get("pnl", 0)) for t in trades if float(t.get("pnl", 0)) < 0))
    if losses <= 0:
        return "inf" if wins > 0 else 0.0
    return round(wins / losses, 4)


def _regime_bucket(regime: str) -> str:
    r = str(regime or "").upper()
    if r in ("RANGE", "RANGING"):
        return "RANGE"
    if r == "TREND":
        return "TREND"
    if r in ("TRANSITION", "HIGH_VOLATILITY", "NO_TRADE"):
        return "TRANSITION"
    return "OTHER"


def _engine_bucket(engine: str) -> str:
    e = str(engine or "").lower()
    if "phase9" in e or "phase99" in e:
        return "phase99"
    if "trend" in e:
        return "trend_engine"
    return "other"


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


def _equity_curve(trades: list[dict[str, Any]], *, initial: float = 10_000.0) -> list[dict[str, Any]]:
    ordered = sorted(trades, key=lambda t: t.get("exit_timestamp") or t.get("timestamp"))
    eq = initial
    points = [{"timestamp": None, "equity": eq}]
    for t in ordered:
        eq += float(t.get("pnl", 0))
        points.append({"timestamp": t.get("exit_timestamp") or t.get("timestamp"), "equity": round(eq, 4)})
    return points


def _streaks(trades: list[dict[str, Any]]) -> dict[str, int]:
    ordered = sorted(trades, key=lambda t: t.get("exit_timestamp") or t.get("timestamp"))
    max_win = max_loss = cur_win = cur_loss = 0
    for t in ordered:
        pnl = float(t.get("pnl", 0))
        if pnl > 0:
            cur_win += 1
            cur_loss = 0
        elif pnl < 0:
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        max_win = max(max_win, cur_win)
        max_loss = max(max_loss, cur_loss)
    return {"longest_winning_streak": max_win, "longest_losing_streak": max_loss}


def build_sample_validation(
    trades: list[dict[str, Any]],
    *,
    collection_meta: dict[str, Any],
) -> dict[str, Any]:
    completed = [t for t in trades if str(t.get("exit_reason", "")).lower() not in ("no_data", "")]
    journal_exec = int(collection_meta.get("journal_executions", 0))
    valid_journal = int(collection_meta.get("valid_journal_trades", 0))
    incomplete_journal = max(0, journal_exec - valid_journal)

    durations = [float(t.get("duration_bars", 0)) for t in completed]
    spreads = [float(t.get("spread", 0)) for t in completed]
    confidences = [float(t.get("confidence", 0)) for t in completed]
    probabilities = [float(t.get("probability", 0)) for t in completed if t.get("probability") is not None]

    regime_counts = Counter(_regime_bucket(t.get("regime", "")) for t in completed)
    direction_counts = Counter(str(t.get("direction", "")) for t in completed)

    return {
        "phase": "26B",
        "total_trades_observed": journal_exec + int(collection_meta.get("replay_signals", 0)),
        "journal_executions": journal_exec,
        "replay_signals_evaluated": int(collection_meta.get("replay_signals", 0)),
        "completed_trades": len(completed),
        "cancelled_or_incomplete": incomplete_journal,
        "analysis_sample_size": len(completed),
        "buy_count": direction_counts.get("BUY", 0),
        "sell_count": direction_counts.get("SELL", 0),
        "range_count": regime_counts.get("RANGE", 0),
        "trend_count": regime_counts.get("TREND", 0),
        "transition_count": regime_counts.get("TRANSITION", 0),
        "average_duration_bars": _mean(durations),
        "median_duration_bars": _median(durations),
        "average_spread": _mean(spreads),
        "average_confidence": _mean(confidences),
        "average_probability": _mean(probabilities),
        "minimum_sample_required": MINIMUM_SAMPLE_SIZE,
        "sample_sufficient": len(completed) >= MINIMUM_SAMPLE_SIZE,
        "note": "Completed trades sourced exclusively from phase26a/trade_log.json — no fabricated records",
    }


def build_performance_metrics(trades: list[dict[str, Any]], *, initial_balance: float = 10_000.0) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"phase": "26B", "completed_trades": 0, "metrics_unavailable": True}

    pnls = [float(t.get("pnl", 0)) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net = sum(pnls)
    equity = _equity_curve(trades, initial=initial_balance)
    max_dd_pct, max_dd_abs = _max_drawdown(equity)
    tf = str(trades[0].get("timeframe", "M5"))
    sharpe = round(_sharpe(equity, tf), 4)
    sortino = round(_sortino(equity, tf), 4)
    ret_pct = (net / initial_balance * 100) if initial_balance else 0.0
    recovery = _recovery_factor(net, max_dd_abs)
    calmar = round(ret_pct / max_dd_pct, 4) if max_dd_pct > 0 else ("inf" if ret_pct > 0 else 0.0)

    # Daily / weekly / monthly returns from equity points
    by_day: dict[str, float] = defaultdict(float)
    for t in trades:
        day = str(t.get("exit_timestamp") or t.get("timestamp"))[:10]
        by_day[day] += float(t.get("pnl", 0))
    daily_returns = [v / initial_balance * 100 for v in by_day.values()]

    by_week: dict[str, float] = defaultdict(float)
    for t in trades:
        dt = _parse_ts(str(t.get("exit_timestamp") or t.get("timestamp")))
        wk = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        by_week[wk] += float(t.get("pnl", 0))
    weekly_returns = [v / initial_balance * 100 for v in by_week.values()]

    by_month: dict[str, float] = defaultdict(float)
    for t in trades:
        mo = str(t.get("exit_timestamp") or t.get("timestamp"))[:7]
        by_month[mo] += float(t.get("pnl", 0))
    monthly_returns = [v / initial_balance * 100 for v in by_month.values()]

    mae_vals = [float(t.get("mae", 0)) for t in trades]
    mfe_vals = [float(t.get("mfe", 0)) for t in trades]
    rr_vals = [float(t.get("rr")) for t in trades if t.get("rr") is not None]

    return {
        "phase": "26B",
        "completed_trades": n,
        "profit_factor": _profit_factor(trades),
        "expectancy": round(net / n, 4),
        "win_rate": round(len(wins) / n, 4),
        "loss_rate": round(len(losses) / n, 4),
        "average_win": round(gross_profit / len(wins), 4) if wins else 0.0,
        "average_loss": round(-gross_loss / len(losses), 4) if losses else 0.0,
        "average_rr": _mean(rr_vals),
        "average_mae": _mean(mae_vals),
        "average_mfe": _mean(mfe_vals),
        "recovery_factor": recovery if recovery != float("inf") else "inf",
        "maximum_drawdown_pct": round(max_dd_pct, 4),
        "maximum_drawdown_abs": round(max_dd_abs, 4),
        "average_daily_return_pct": _mean(daily_returns),
        "average_weekly_return_pct": _mean(weekly_returns),
        "average_monthly_return_pct": _mean(monthly_returns),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "net_profit": round(net, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
    }


def build_confidence_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    conf = [float(t.get("confidence", 0)) for t in trades]
    prob = [float(t.get("probability", 0)) for t in trades if t.get("probability") is not None]
    pnl = [float(t.get("pnl", 0)) for t in trades]
    pnl_r = [float(t.get("pnl_r", 0)) for t in trades]

    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        c = float(t.get("confidence", 0))
        if c < 0.5:
            key = "low_<0.5"
        elif c < 0.75:
            key = "mid_0.5_0.75"
        else:
            key = "high_>=0.75"
        buckets[key].append(float(t.get("pnl", 0)))

    bucket_expectancy = {k: round(sum(v) / len(v), 4) if v else 0.0 for k, v in buckets.items()}
    higher_conf_better = None
    if len(buckets) >= 2 and all(len(v) > 0 for v in buckets.values()):
        higher_conf_better = bucket_expectancy.get("high_>=0.75", 0) >= bucket_expectancy.get("low_<0.5", 0)

    return {
        "phase": "26B",
        "sample_size": len(trades),
        "distributions": {
            "confidence": {"count": len(conf), "histogram": _histogram(conf), "mean": _mean(conf)},
            "probability": {"count": len(prob), "histogram": _histogram(prob), "mean": _mean(prob)},
            "pnl": {"count": len(pnl), "histogram": _histogram(pnl), "mean": _mean(pnl)},
            "pnl_r": {"count": len(pnl_r), "histogram": _histogram(pnl_r), "mean": _mean(pnl_r)},
        },
        "confidence_bucket_expectancy": bucket_expectancy,
        "higher_confidence_higher_expectancy": higher_conf_better,
        "conclusion": (
            "inconclusive — insufficient sample for confidence-expectancy validation"
            if len(trades) < MINIMUM_SAMPLE_SIZE
            else "see bucket_expectancy"
        ),
    }


def _regime_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "pf": 0.0, "expectancy": 0.0, "win_rate": 0.0, "average_rr": 0.0, "drawdown_pct": 0.0}
    equity = _equity_curve(trades)
    dd_pct, _ = _max_drawdown(equity)
    wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
    rr = [float(t.get("rr")) for t in trades if t.get("rr") is not None]
    net = sum(float(t.get("pnl", 0)) for t in trades)
    return {
        "trades": n,
        "pf": _profit_factor(trades),
        "expectancy": round(net / n, 4),
        "win_rate": round(wins / n, 4),
        "average_rr": _mean(rr),
        "drawdown_pct": round(dd_pct, 4),
    }


def build_regime_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        buckets[_regime_bucket(t.get("regime", ""))].append(t)
    return {
        "phase": "26B",
        "RANGE": _regime_metrics(buckets.get("RANGE", [])),
        "TREND": _regime_metrics(buckets.get("TREND", [])),
        "TRANSITION": _regime_metrics(buckets.get("TRANSITION", [])),
        "OTHER": _regime_metrics(buckets.get("OTHER", [])),
    }


def build_engine_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        buckets[_engine_bucket(t.get("engine", ""))].append(t)

    def _engine_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        if n == 0:
            return {"trades": 0, "pf": 0.0, "expectancy": 0.0, "average_confidence": 0.0, "win_rate": 0.0, "average_duration_bars": 0.0}
        wins = sum(1 for t in rows if float(t.get("pnl", 0)) > 0)
        net = sum(float(t.get("pnl", 0)) for t in rows)
        return {
            "trades": n,
            "pf": _profit_factor(rows),
            "expectancy": round(net / n, 4),
            "average_confidence": _mean([float(t.get("confidence", 0)) for t in rows]),
            "win_rate": round(wins / n, 4),
            "average_duration_bars": _mean([float(t.get("duration_bars", 0)) for t in rows]),
        }

    return {
        "phase": "26B",
        "phase99": _engine_stats(buckets.get("phase99", [])),
        "trend_engine": _engine_stats(buckets.get("trend_engine", [])),
        "other": _engine_stats(buckets.get("other", [])),
    }


def build_time_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    by_hour: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_dow: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for t in trades:
        dt = _parse_ts(str(t.get("timestamp")))
        by_hour[dt.hour].append(t)
        by_dow[dt.strftime("%A")].append(t)
        by_session[_session(dt.hour)].append(t)

    def _perf(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"trades": 0, "expectancy": 0.0, "pf": 0.0}
        net = sum(float(t.get("pnl", 0)) for t in rows)
        return {"trades": len(rows), "expectancy": round(net / len(rows), 4), "pf": _profit_factor(rows)}

    hour_stats = {str(h): _perf(rows) for h, rows in sorted(by_hour.items())}
    dow_stats = {d: _perf(rows) for d, rows in sorted(by_dow.items())}
    session_stats = {s: _perf(rows) for s, rows in sorted(by_session.items())}

    strongest_session = max(session_stats.items(), key=lambda x: x[1]["expectancy"])[0] if session_stats else None
    strongest_hour = max(hour_stats.items(), key=lambda x: x[1]["expectancy"])[0] if hour_stats else None

    return {
        "phase": "26B",
        "by_hour_utc": hour_stats,
        "by_day_of_week": dow_stats,
        "by_session": session_stats,
        "sessions": {
            "Asian": session_stats.get("Asian", {}),
            "London": session_stats.get("London", {}),
            "New York": session_stats.get("New York", {}),
            "Overlap": session_stats.get("Overlap", {}),
        },
        "strongest_session": strongest_session,
        "strongest_hour_utc": strongest_hour,
        "note": "Single-trade sample — session rankings not statistically meaningful",
    }


def build_risk_analysis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {"phase": "26B", "trades": 0}

    lots = [float(t.get("lot", 0)) for t in trades]
    pnls = [float(t.get("pnl", 0)) for t in trades]
    risk_pcts = [float(t.get("risk_percent", 0)) for t in trades if t.get("risk_percent") is not None]
    streaks = _streaks(trades)

    return {
        "phase": "26B",
        "trades": len(trades),
        "average_risk_percent": _mean(risk_pcts),
        "average_lot": _mean(lots),
        "largest_loss": round(min(pnls), 4) if pnls else 0.0,
        "largest_win": round(max(pnls), 4) if pnls else 0.0,
        **streaks,
    }


def build_stability_analysis(trades: list[dict[str, Any]], *, window: int = 20) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: t.get("exit_timestamp") or t.get("timestamp"))
    rolling_pf: list[dict[str, Any]] = []
    rolling_exp: list[dict[str, Any]] = []
    rolling_wr: list[dict[str, Any]] = []

    for i in range(len(ordered)):
        start = max(0, i - window + 1)
        chunk = ordered[start : i + 1]
        ts = ordered[i].get("exit_timestamp") or ordered[i].get("timestamp")
        wins = sum(1 for t in chunk if float(t.get("pnl", 0)) > 0)
        net = sum(float(t.get("pnl", 0)) for t in chunk)
        rolling_pf.append({"timestamp": ts, "value": _profit_factor(chunk), "window_trades": len(chunk)})
        rolling_exp.append({"timestamp": ts, "value": round(net / len(chunk), 4), "window_trades": len(chunk)})
        rolling_wr.append({"timestamp": ts, "value": round(wins / len(chunk), 4), "window_trades": len(chunk)})

    degradation_detected = False
    if len(rolling_exp) >= 2:
        degradation_detected = rolling_exp[-1]["value"] < rolling_exp[0]["value"]

    return {
        "phase": "26B",
        "rolling_window": window,
        "rolling_pf": rolling_pf,
        "rolling_expectancy": rolling_exp,
        "rolling_win_rate": rolling_wr,
        "degradation_detected": degradation_detected,
        "stability_assessment": (
            "insufficient_sample_for_stability_analysis"
            if len(trades) < MINIMUM_SAMPLE_SIZE
            else "monitor_rolling_metrics"
        ),
    }


def build_minimum_sample_report(completed_count: int) -> dict[str, Any]:
    sufficient = completed_count >= MINIMUM_SAMPLE_SIZE
    return {
        "phase": "26B",
        "completed_trades": completed_count,
        "minimum_required": MINIMUM_SAMPLE_SIZE,
        "verdict": "INSUFFICIENT_SAMPLE" if not sufficient else "SAMPLE_OK",
        "optimization_recommendations_allowed": sufficient,
        "message": (
            f"Completed trades ({completed_count}) below minimum ({MINIMUM_SAMPLE_SIZE}). "
            "Statistics reported only — no optimization recommendations."
            if not sufficient
            else "Sample size meets minimum threshold."
        ),
    }
