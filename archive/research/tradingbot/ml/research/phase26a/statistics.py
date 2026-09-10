"""Aggregate paper trade statistics (research-only)."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from tradingbot.ml.research.phase26a.trade_schema import CompletedPaperTrade


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def _profit_factor(trades: list[CompletedPaperTrade]) -> float | str:
    wins = sum(t.pnl for t in trades if t.pnl > 0)
    losses = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if losses <= 0:
        return "inf" if wins > 0 else 0.0
    return round(wins / losses, 4)


def _core_stats(trades: list[CompletedPaperTrade]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "average_rr": 0.0,
            "average_holding_bars": 0.0,
            "average_confidence": 0.0,
            "average_probability": 0.0,
            "average_spread": 0.0,
            "average_atr": 0.0,
            "average_adx": 0.0,
            "average_rsi": 0.0,
        }

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    rr_vals = [t.rr for t in trades if t.rr is not None]
    conf = [t.confidence for t in trades]
    prob = [t.probability for t in trades if t.probability is not None]
    spread = [t.spread for t in trades]
    atr = [t.atr for t in trades if t.atr is not None]
    adx = [t.adx for t in trades if t.adx is not None]
    rsi = [t.rsi for t in trades if t.rsi is not None]

    return {
        "trades": n,
        "win_rate": round(len(wins) / n, 4),
        "loss_rate": round(len(losses) / n, 4),
        "profit_factor": _profit_factor(trades),
        "expectancy": round(sum(t.pnl for t in trades) / n, 4),
        "average_rr": _mean([float(x) for x in rr_vals]),
        "average_holding_bars": _mean([float(t.duration_bars) for t in trades]),
        "average_confidence": _mean(conf),
        "average_probability": _mean(prob),
        "average_spread": _mean(spread),
        "average_atr": _mean(atr),
        "average_adx": _mean(adx),
        "average_rsi": _mean(rsi),
    }


def _distribution(trades: list[CompletedPaperTrade], key: str) -> dict[str, int]:
    return dict(Counter(getattr(t, key, "UNKNOWN") or "UNKNOWN" for t in trades))


def build_daily_statistics(trades: list[CompletedPaperTrade]) -> dict[str, Any]:
    buckets: dict[str, list[CompletedPaperTrade]] = defaultdict(list)
    for t in trades:
        day = str(t.timestamp)[:10]
        buckets[day].append(t)

    days = {}
    for day, rows in sorted(buckets.items()):
        stats = _core_stats(rows)
        days[day] = {
            **stats,
            "regime_distribution": _distribution(rows, "regime"),
            "direction_distribution": _distribution(rows, "direction"),
        }

    return {"phase": "26A", "days": days, "summary": _core_stats(trades)}


def build_weekly_statistics(trades: list[CompletedPaperTrade]) -> dict[str, Any]:
    buckets: dict[str, list[CompletedPaperTrade]] = defaultdict(list)
    for t in trades:
        dt = datetime.fromisoformat(str(t.timestamp).replace("Z", "+00:00"))
        week = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        buckets[week].append(t)

    weeks = {wk: {**_core_stats(rows), "regime_distribution": _distribution(rows, "regime")} for wk, rows in sorted(buckets.items())}
    return {"phase": "26A", "weeks": weeks, "summary": _core_stats(trades)}


def build_monthly_statistics(trades: list[CompletedPaperTrade]) -> dict[str, Any]:
    buckets: dict[str, list[CompletedPaperTrade]] = defaultdict(list)
    for t in trades:
        month = str(t.timestamp)[:7]
        buckets[month].append(t)

    months = {m: {**_core_stats(rows), "regime_distribution": _distribution(rows, "regime")} for m, rows in sorted(buckets.items())}
    return {"phase": "26A", "months": months, "summary": _core_stats(trades)}


def build_equity_curve(trades: list[CompletedPaperTrade], *, initial_balance: float = 10_000.0) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: t.exit_timestamp or t.timestamp)
    equity = initial_balance
    points: list[dict[str, Any]] = [{"timestamp": None, "equity": equity, "trade_index": 0}]
    for i, t in enumerate(ordered, start=1):
        equity += t.pnl
        points.append(
            {
                "timestamp": t.exit_timestamp or t.timestamp,
                "equity": round(equity, 4),
                "trade_index": i,
                "pnl": t.pnl,
            }
        )
    return {"phase": "26A", "initial_balance": initial_balance, "final_balance": round(equity, 4), "points": points}


def build_drawdown_curve(equity_curve: dict[str, Any]) -> dict[str, Any]:
    points = equity_curve.get("points", [])
    peak = -float("inf")
    dd_points: list[dict[str, Any]] = []
    max_dd = 0.0
    for p in points:
        eq = float(p.get("equity", 0))
        peak = max(peak, eq)
        dd_abs = peak - eq
        dd_pct = (dd_abs / peak * 100) if peak > 0 else 0.0
        max_dd = max(max_dd, dd_pct)
        dd_points.append(
            {
                "timestamp": p.get("timestamp"),
                "equity": eq,
                "drawdown_abs": round(dd_abs, 4),
                "drawdown_pct": round(dd_pct, 4),
            }
        )
    return {"phase": "26A", "max_drawdown_pct": round(max_dd, 4), "points": dd_points}


def build_trade_sequence(trades: list[CompletedPaperTrade]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: t.exit_timestamp or t.timestamp)
    return {
        "phase": "26A",
        "count": len(ordered),
        "sequence": [
            {
                "index": i + 1,
                "timestamp": t.timestamp,
                "exit_timestamp": t.exit_timestamp,
                "direction": t.direction,
                "regime": t.regime,
                "engine": t.engine,
                "pnl": t.pnl,
                "pnl_r": t.pnl_r,
                "exit_reason": t.exit_reason,
            }
            for i, t in enumerate(ordered)
        ],
    }


def _regime_bucket_stats(trades: list[CompletedPaperTrade]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "profit_factor": 0.0, "expectancy": 0.0, "win_rate": 0.0, "average_rr": 0.0}
    stats = _core_stats(trades)
    return {
        "trades": stats["trades"],
        "profit_factor": stats["profit_factor"],
        "expectancy": stats["expectancy"],
        "win_rate": stats["win_rate"],
        "average_rr": stats["average_rr"],
    }


def build_regime_statistics(trades: list[CompletedPaperTrade]) -> dict[str, dict[str, Any]]:
    range_trades = [t for t in trades if str(t.regime).upper() in ("RANGE", "RANGING")]
    trend_trades = [t for t in trades if str(t.regime).upper() == "TREND"]
    transition_trades = [t for t in trades if str(t.regime).upper() in ("TRANSITION", "HIGH_VOLATILITY", "NO_TRADE")]

    return {
        "range_statistics.json": {"phase": "26A", **_regime_bucket_stats(range_trades)},
        "trend_statistics.json": {"phase": "26A", **_regime_bucket_stats(trend_trades)},
        "transition_statistics.json": {"phase": "26A", **_regime_bucket_stats(transition_trades)},
    }


def build_model_statistics(trades: list[CompletedPaperTrade]) -> dict[str, dict[str, Any]]:
    phase99 = [t for t in trades if "phase9" in str(t.engine).lower() or str(t.regime).upper() in ("RANGE", "RANGING")]
    trend = [t for t in trades if "trend" in str(t.engine).lower() or str(t.regime).upper() == "TREND"]

    return {
        "phase99_statistics.json": {"phase": "26A", "engine": "phase9_9", **_regime_bucket_stats(phase99)},
        "trend_statistics_model.json": {"phase": "26A", "engine": "trend_rf_v41", **_regime_bucket_stats(trend)},
    }
