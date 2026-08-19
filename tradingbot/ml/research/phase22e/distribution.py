"""Phase 22E — trade distribution analytics."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tradingbot.backtest.models import ClosedTrade
from tradingbot.ml.research.phase22e.metrics import is_range_trade, is_trend_trade

TEHRAN = ZoneInfo("Asia/Tehran")


def _to_tehran(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        from datetime import timezone

        return ts.replace(tzinfo=timezone.utc).astimezone(TEHRAN)
    return ts.astimezone(TEHRAN)


def _streaks(trades: list[ClosedTrade], *, wins: bool) -> dict[str, int]:
    best = cur = 0
    for t in trades:
        hit = t.pnl > 0 if wins else t.pnl < 0
        if hit:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return {"max": best, "current": cur}


def compute_trade_distribution(trades: list[ClosedTrade], *, label: str = "combined") -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "label": label,
            "total_trades": 0,
            "buy_pct": 0.0,
            "sell_pct": 0.0,
            "trend_pct": 0.0,
            "range_pct": 0.0,
            "long_win_streaks": {"max": 0, "current": 0},
            "short_loss_streaks": {"max": 0, "current": 0},
            "monthly_trades": {},
            "weekly_trades": {},
            "daily_trades": {},
        }

    buys = sum(1 for t in trades if t.is_buy)
    trend = sum(1 for t in trades if is_trend_trade(t))
    rng = sum(1 for t in trades if is_range_trade(t))

    monthly: Counter[str] = Counter()
    weekly: Counter[str] = Counter()
    daily: Counter[str] = Counter()

    for t in trades:
        local = _to_tehran(t.entry_time)
        monthly[local.strftime("%Y-%m")] += 1
        weekly[local.strftime("%Y-W%W")] += 1
        daily[local.strftime("%Y-%m-%d")] += 1

    return {
        "label": label,
        "total_trades": n,
        "buy_pct": round(buys / n * 100, 2),
        "sell_pct": round((n - buys) / n * 100, 2),
        "trend_pct": round(trend / n * 100, 2),
        "range_pct": round(rng / n * 100, 2),
        "long_win_streaks": _streaks(trades, wins=True),
        "short_loss_streaks": _streaks(trades, wins=False),
        "monthly_trades": dict(sorted(monthly.items())),
        "weekly_trades": dict(sorted(weekly.items())),
        "daily_trades": dict(sorted(daily.items())),
        "avg_trades_per_month": round(n / max(1, len(monthly)), 2),
        "avg_trades_per_week": round(n / max(1, len(weekly)), 2),
        "avg_trades_per_day": round(n / max(1, len(daily)), 2),
    }


def aggregate_distribution(per_tf_results: dict[str, list[ClosedTrade]]) -> dict[str, Any]:
    combined: list[ClosedTrade] = []
    by_tf = {}
    for tf, trades in per_tf_results.items():
        by_tf[tf] = compute_trade_distribution(trades, label=tf)
        combined.extend(trades)
    combined.sort(key=lambda t: t.entry_time)
    return {
        "per_timeframe": by_tf,
        "portfolio_combined": compute_trade_distribution(combined, label="portfolio"),
    }
