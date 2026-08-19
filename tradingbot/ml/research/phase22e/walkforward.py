"""Phase 22E — chronological walk-forward validation."""

from __future__ import annotations

from typing import Any

from tradingbot.backtest.models import ClosedTrade
from tradingbot.backtest.models import BacktestResult
from tradingbot.ml.research.phase22e.config import WALK_FORWARD_FOLDS
from tradingbot.ml.research.phase22e.metrics import compute_extended_metrics


def _chronological_folds(trades: list[ClosedTrade], n_folds: int) -> list[tuple[list[ClosedTrade], list[ClosedTrade]]]:
    ordered = sorted(trades, key=lambda t: t.entry_time)
    n = len(ordered)
    if n < n_folds * 3:
        mid = max(1, n // 2)
        return [(ordered[:mid], ordered[mid:])]
    fold_size = max(1, n // (n_folds + 1))
    folds = []
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_end = min(n, train_end + fold_size)
        train = ordered[:train_end]
        test = ordered[train_end:test_end]
        if train and test:
            folds.append((train, test))
    return folds


def run_walkforward(
    trades: list[ClosedTrade],
    *,
    initial_balance: float = 200.0,
    timeframe: str = "M5",
    n_folds: int = WALK_FORWARD_FOLDS,
) -> dict[str, Any]:
    """Pure chronological walk-forward — no shuffling."""
    accepted = sorted(trades, key=lambda t: t.entry_time)
    folds = _chronological_folds(accepted, n_folds)
    fold_results: list[dict[str, Any]] = []
    stable = 0

    for idx, (_train, test) in enumerate(folds):
        stub = BacktestResult(
            config=None,
            initial_balance=initial_balance,
            final_balance=initial_balance + sum(t.pnl for t in test),
            trades=test,
            equity_curve=[
                {"equity": initial_balance + sum(t.pnl for t in test[: i + 1])}
                for i in range(len(test))
            ]
            if test
            else [{"equity": initial_balance}],
        )
        perf = compute_extended_metrics(stub, timeframe)
        pf = perf.get("profit_factor")
        pf_val = float(pf) if pf not in ("inf", None) else 999.0
        exp = float(perf.get("expectancy", 0))
        ok = pf_val >= 1.0 and exp >= 0
        if ok:
            stable += 1
        fold_results.append({
            "fold": idx,
            "train_trades": len(_train),
            "test_trades": len(test),
            "profit_factor": pf,
            "expectancy": perf.get("expectancy"),
            "average_r": perf.get("average_r"),
            "max_drawdown_pct": perf.get("max_drawdown_pct"),
            "win_rate_pct": perf.get("win_rate_pct"),
            "stable": ok,
        })

    return {
        "phase": "22E",
        "method": "chronological_walk_forward",
        "shuffled": False,
        "n_folds": len(folds),
        "stable_folds": stable,
        "stable": stable >= max(1, len(folds) * 3 // 4),
        "passed": stable >= max(1, len(folds) // 2) and len(accepted) >= 10,
        "folds": fold_results,
        "total_trades": len(accepted),
    }
