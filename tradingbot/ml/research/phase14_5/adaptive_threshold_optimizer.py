"""Phase 14.5 — adaptive threshold composite scoring."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.research.phase14_5.config import MIN_TRADE_FLOOR


def composite_score(
    metrics: dict[str, Any],
    *,
    robustness: float = 0.5,
    train_test_gap: float = 0.0,
) -> float:
    """
    score = 30% expectancy + 25% robustness + 20% trade stability + 15% drawdown + 10% precision
  Penalize <300 trades and train/test gap.
    """
    trades = int(metrics.get("effective_trades_est", metrics.get("trades", 0)))
    if trades < MIN_TRADE_FLOOR:
        return 0.0

    exp = float(metrics.get("expectancy", 0.0))
    exp_norm = min(max(exp + 1.0, 0.0), 2.0) / 2.0
    rob = min(max(float(robustness), 0.0), 1.0)
    stability = min(trades / 500.0, 1.0)
    dd = 1.0 - min(float(metrics.get("max_drawdown", 1.0)), 1.0)
    prec = min(float(metrics.get("precision", 0.0)), 1.0)

    raw = exp_norm * 0.30 + rob * 0.25 + stability * 0.20 + dd * 0.15 + prec * 0.10
    gap_penalty = min(float(train_test_gap), 0.5)
    return round(max(0.0, raw - gap_penalty), 4)


def select_best_threshold(sweep_results: list[dict[str, Any]], *, wf_scores: dict[float, float] | None = None) -> dict[str, Any] | None:
    wf = wf_scores or {}
    ranked: list[dict[str, Any]] = []
    for row in sweep_results:
        if row.get("rejected"):
            continue
        th = float(row["confidence_threshold"])
        score = composite_score(row, robustness=wf.get(th, 0.5))
        ranked.append({**row, "composite_score": score, "walk_forward_score": wf.get(th, 0.5)})

    if not ranked:
        return None
    ranked.sort(key=lambda r: r["composite_score"], reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked[0]


def rank_thresholds(
    sweep_results: list[dict[str, Any]],
    *,
    wf_scores: dict[float, float] | None = None,
) -> list[dict[str, Any]]:
    wf = wf_scores or {}
    ranked: list[dict[str, Any]] = []
    for row in sweep_results:
        if row.get("rejected"):
            continue
        th = float(row["confidence_threshold"])
        ranked.append(
            {
                **row,
                "composite_score": composite_score(row, robustness=wf.get(th, 0.5)),
                "walk_forward_score": wf.get(th, 0.5),
            }
        )
    ranked.sort(key=lambda r: r["composite_score"], reverse=True)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked
