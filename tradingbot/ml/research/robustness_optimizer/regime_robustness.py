"""Phase 9.9 — per-regime robustness analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.regime_optimization.regime_utils import (
    REGIMES,
    assign_market_regime,
    trading_metrics_from_labels,
)


def _group_label(regime: str) -> str:
    if regime in ("TREND_UP", "TREND_DOWN"):
        return "TREND"
    if regime in ("HIGH_VOLATILITY", "LOW_VOLATILITY"):
        return "VOLATILITY"
    return regime


def analyze_regime_robustness(df: pd.DataFrame) -> dict[str, Any]:
    """Measure win rate, expectancy, PF per market regime (causal labels only)."""
    work = df.copy()
    work["market_regime"] = assign_market_regime(work)
    by_regime: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {g: [] for g in ("RANGE", "TREND", "VOLATILITY")}

    for regime in REGIMES:
        subset = work.loc[work["market_regime"] == regime]
        if subset.empty:
            continue
        metrics = trading_metrics_from_labels(subset["label"].astype(int).to_numpy())
        wins = int((subset["label"] == int(Label.TP_FIRST)).sum())
        row = {
            "regime": regime,
            "group": _group_label(regime),
            "sample_count": len(subset),
            "win_rate": metrics["win_rate"],
            "expectancy": metrics["expectancy"],
            "profit_factor": metrics["profit_factor_proxy"],
            "max_drawdown_proxy": metrics["max_drawdown_proxy"],
        }
        by_regime.append(row)
        grouped[_group_label(regime)].append(row)

    group_summary: list[dict[str, Any]] = []
    for group, rows in grouped.items():
        if not rows:
            continue
        total = sum(r["sample_count"] for r in rows)
        weighted_exp = sum(r["expectancy"] * r["sample_count"] for r in rows) / total
        weighted_pf = sum(r["profit_factor"] * r["sample_count"] for r in rows) / total
        group_summary.append(
            {
                "group": group,
                "sample_count": total,
                "expectancy": round(weighted_exp, 4),
                "profit_factor": round(weighted_pf, 4),
                "regimes": [r["regime"] for r in rows],
            }
        )

    ranked = sorted(by_regime, key=lambda r: (-r["expectancy"], -r["profit_factor"]))
    best = ranked[0] if ranked else None
    return {
        "by_regime": by_regime,
        "group_summary": group_summary,
        "best_regime": best["regime"] if best else None,
        "recommended_filter_regime": best["regime"] if best and best["expectancy"] > 0 else "RANGE",
    }
