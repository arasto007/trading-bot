"""Phase 22E validation tests — deterministic certification logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tradingbot.backtest.models import ClosedTrade
from tradingbot.ml.research.phase22e.certification import assess_live_readiness
from tradingbot.ml.research.phase22e.config import compute_windows
from tradingbot.ml.research.phase22e.distribution import compute_trade_distribution
from tradingbot.ml.research.phase22e.metrics import compute_extended_metrics, is_trend_trade
from tradingbot.backtest.models import BacktestResult
from tradingbot.ml.research.phase22e.walkforward import run_walkforward


def _trade(pnl: float, *, is_buy: bool = True, strategy: str = "trend_rf_v41") -> ClosedTrade:
    return ClosedTrade(
        symbol="XAUUSD",
        is_buy=is_buy,
        entry_price=2000.0,
        exit_price=2001.0,
        volume=0.01,
        entry_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        exit_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        pnl=pnl,
        reason="tp",
        strategy=strategy,
        r_multiple=pnl / 10.0,
    )


def test_compute_windows_chronological():
    windows = compute_windows()
    labels = [w.label for w in windows]
    assert labels == ["1m", "3m", "6m", "1y", "3y"]
    for w in windows:
        assert w.end > w.start


def test_extended_metrics_certification():
    trades = [_trade(20), _trade(-10, is_buy=False, strategy="phase9_9")]
    result = BacktestResult(
        config=None,
        initial_balance=200.0,
        final_balance=210.0,
        trades=trades,
        equity_curve=[{"equity": 200}, {"equity": 220}, {"equity": 210}],
    )
    m = compute_extended_metrics(result, "M5")
    assert m["buy_trades"] == 1
    assert m["sell_trades"] == 1
    assert is_trend_trade(trades[0])
    assert m["certification"]["buy_active"]


def test_walkforward_no_shuffle():
    trades = [_trade(i - 3) for i in range(20)]
    wf = run_walkforward(trades, n_folds=4)
    assert wf["shuffled"] is False
    assert wf["n_folds"] >= 1


def test_trade_distribution_streaks():
    trades = [_trade(5), _trade(3), _trade(-2), _trade(-4)]
    d = compute_trade_distribution(trades)
    assert d["total_trades"] == 4
    assert d["long_win_streaks"]["max"] == 2
    assert d["short_loss_streaks"]["max"] == 2


def test_live_readiness_verdict():
    readiness = assess_live_readiness(
        profitability={
            "activity": {"buy_active": True, "sell_active": True, "m5_active": True, "m15_active": True, "h4_active": True},
            "certification_summary": {"pf_target_met": True, "positive_expectancy": True, "max_dd_within_limit": True},
        },
        portfolio={"metrics": {"net_profit": 10}},
        walkforward={"stable": True, "passed": True},
        montecarlo={"passed": True},
        stress={"overall_passed": True},
        delta={"no_regression_vs_22d": True},
    )
    assert readiness["verdict"] == "READY_FOR_DEMO_FORWARD_VALIDATION"
