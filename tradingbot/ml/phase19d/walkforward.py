"""Phase 19D — walk-forward certification."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19d.config import WALK_FORWARD_FOLDS


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


def run_walkforward_certification(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Walk-forward on accepted production trades (filters already applied in path).
    Reject instability when majority of folds show negative expectancy or PF < 1.
    """
    accepted = [t for t in trades if t.get("allowed")]
    folds = _chronological_folds(accepted)
    fold_results: list[dict[str, Any]] = []
    stable_folds = 0

    for idx, (_train, test) in enumerate(folds):
        perf = compute_performance(test)
        stable = perf["profit_factor"] >= 1.0 and perf["expectancy_r"] >= 0
        if stable:
            stable_folds += 1
        fold_results.append({
            "fold": idx,
            "trades": perf["trades"],
            "profit_factor": perf["profit_factor"],
            "expectancy_r": perf["expectancy_r"],
            "maximum_drawdown_r": perf["maximum_drawdown_r"],
            "stable": stable,
        })

    stable = stable_folds >= max(1, len(folds) * 3 // 4)
    return {
        "phase": "19D",
        "n_folds": len(folds),
        "stable_folds": stable_folds,
        "stable": stable,
        "passed": stable and len(accepted) >= 15,
        "folds": fold_results,
    }
