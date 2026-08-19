"""Phase 19C — walk-forward validation for combined RSI+ADX filters."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19c.config import WALK_FORWARD_FOLDS
from tradingbot.ml.phase19c.filters import apply_profitability_filters, load_filter_settings


def _chronological_folds(trades: list[dict], n_folds: int = WALK_FORWARD_FOLDS) -> list[tuple[list, list]]:
    ordered = sorted(trades, key=lambda t: t["timestamp"])
    n = len(ordered)
    if n < n_folds * 5:
        return [(ordered[: max(1, n // 2)], ordered[max(1, n // 2):])]
    fold_size = n // (n_folds + 1)
    folds = []
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_end = min(n, train_end + fold_size)
        train = ordered[:train_end]
        test = ordered[train_end:test_end]
        if train and test:
            folds.append((train, test))
    return folds


def _apply_combined_filter(trade: dict[str, Any], settings=None) -> bool:
    features = {
        "rsi": trade.get("rsi", 50),
        "adx": trade.get("adx", 0),
    }
    return apply_profitability_filters(features, settings=settings).passed


def run_walkforward(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Walk-forward validation for combined RSI mid + ADX band filters.
    Fixed thresholds — no train-set fitting (same as Phase 19B validation).
    """
    settings = load_filter_settings()
    pipeline_trades = [t for t in trades if t.get("pipeline_allowed")]
    if not pipeline_trades:
        pipeline_trades = [t for t in trades if t.get("allowed") or t.get("pipeline_allowed") is not False]

    folds = _chronological_folds(pipeline_trades)
    fold_results: list[dict[str, Any]] = []
    stable_folds = 0

    for idx, (_train, test) in enumerate(folds):
        baseline = compute_performance(test)
        kept = [t for t in test if _apply_combined_filter(t, settings)]
        filtered = compute_performance(kept)
        improved = (
            filtered["profit_factor"] >= baseline["profit_factor"]
            and filtered["expectancy_r"] >= baseline["expectancy_r"]
        )
        if improved:
            stable_folds += 1
        fold_results.append({
            "fold": idx,
            "test_trades": baseline["trades"],
            "filtered_trades": filtered["trades"],
            "baseline_pf": baseline["profit_factor"],
            "filtered_pf": filtered["profit_factor"],
            "baseline_exp": baseline["expectancy_r"],
            "filtered_exp": filtered["expectancy_r"],
            "improved": improved,
        })

    stable = stable_folds >= max(1, len(folds) // 2)
    return {
        "phase": "19C",
        "filter": "rsi_mid+adx_15_50",
        "n_folds": len(folds),
        "stable_folds": stable_folds,
        "stable": stable,
        "folds": fold_results,
    }
