"""Phase 11.5 — threshold sweep on historical paper data (model unchanged)."""

from __future__ import annotations

from itertools import product
from typing import Any

from tradingbot.ml.research.phase11_5._metrics import trade_metrics

BUY_THRESHOLDS = (0.50, 0.52, 0.55, 0.57, 0.60)
SELL_THRESHOLDS = (0.40, 0.43, 0.45, 0.47, 0.50)


def _would_signal(prob: float, buy_t: float, sell_t: float) -> str:
    if prob >= buy_t:
        return "BUY"
    if prob <= sell_t:
        return "SELL"
    return "HOLD"


def optimize_thresholds(
    trades: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for buy_t, sell_t in product(BUY_THRESHOLDS, SELL_THRESHOLDS):
        if buy_t <= sell_t:
            continue
        filtered = [
            t
            for t in trades
            if t.get("ml_probability") is not None
            and _would_signal(float(t["ml_probability"]), buy_t, sell_t) == t.get("direction")
        ]
        signal_count = sum(
            1
            for c in cycles
            if c.get("ml_probability") is not None
            and _would_signal(float(c["ml_probability"]), buy_t, sell_t) != "HOLD"
        )
        metrics = trade_metrics(filtered)
        row = {
            "buy_threshold": buy_t,
            "sell_threshold": sell_t,
            "signal_count": signal_count,
            **metrics,
        }
        results.append(row)
        if best is None or (
            metrics["profit_factor"] > best.get("profit_factor", 0)
            and metrics["trades"] >= 10
        ):
            best = row

    current = next(
        (r for r in results if r["buy_threshold"] == 0.55 and r["sell_threshold"] == 0.45),
        results[0] if results else {},
    )
    return {
        "current_thresholds": {"buy": 0.55, "sell": 0.45, **current},
        "best_thresholds": best,
        "grid": results,
        "recommendation": (
            f"Consider buy={best['buy_threshold']} sell={best['sell_threshold']}"
            if best and best != current
            else "Current 0.55/0.45 remains competitive on paper data"
        ),
    }
