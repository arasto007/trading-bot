"""Phase 13.8 — trend ML threshold optimization."""

from __future__ import annotations

from typing import Any, Callable

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_8.config import MIN_TRADES_SOFT, MIN_TRADES_STRONG, THRESHOLD_GRID
from tradingbot.ml.research.phase13_8.trend_comparator import run_variant_backtest
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def _robust_score(metrics: dict[str, Any], *, wf: float = 0.5) -> float:
    trades = int(metrics.get("trades", 0))
    if trades < MIN_TRADES_SOFT:
        return 0.0
    pf = min(float(metrics.get("profit_factor", 0.0)), 3.0) / 3.0
    exp = min(max(float(metrics.get("expectancy", 0.0)) + 1.0, 0.0), 2.0) / 2.0
    dd = 1.0 - min(float(metrics.get("max_drawdown", 1.0)), 1.0)
    consistency = min(trades / 500.0, 1.0)
    return round(pf * 0.25 + exp * 0.20 + wf * 0.30 + consistency * 0.15 + dd * 0.10, 4)


def optimize_threshold(
    frame: pd.DataFrame,
    *,
    symbol: str,
    rule_fn: Callable[..., str],
    model: Any,
    scaler: Any,
    model_name: str,
    wf_score: float = 0.5,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    for threshold in THRESHOLD_GRID:
        th = threshold

        def make_filter(threshold_value: float):
            def _f(row: pd.Series, direction: str) -> bool:
                ml = apply_trend_ml_filter(
                    row, model=model, scaler=scaler, model_name=model_name, threshold=threshold_value
                )
                return bool(ml["allow_trade"])

            return _f

        bt = run_variant_backtest(frame, symbol=symbol, rule_fn=rule_fn, ml_filter=make_filter(th))
        m = bt["metrics"]
        trades = int(m.get("trades", 0))
        status = "pass"
        if trades < MIN_TRADES_SOFT:
            status = "reject"
        elif trades < MIN_TRADES_STRONG:
            status = "weak"
        score = _robust_score(m, wf=wf_score) if trades >= MIN_TRADES_SOFT else 0.0
        rows.append(
            {
                "threshold": threshold,
                "metrics": m,
                "trades": trades,
                "status": status,
                "robust_score": score,
            }
        )

    ranked = sorted(rows, key=lambda r: r["robust_score"], reverse=True)
    best = ranked[0] if ranked else {"threshold": 0.50, "robust_score": 0.0}
    return {
        "candidates": list(THRESHOLD_GRID),
        "ranking": ranked,
        "best_threshold": best["threshold"],
        "best_robust_score": best.get("robust_score", 0.0),
        "trade_floor": {"soft": MIN_TRADES_SOFT, "strong": MIN_TRADES_STRONG},
    }
