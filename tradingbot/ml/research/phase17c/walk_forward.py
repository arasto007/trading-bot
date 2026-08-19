"""Phase 17C — chronological walk-forward by calendar year."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.phase17c.config import RF_THRESHOLD, WALK_FORWARD_YEARS
from tradingbot.ml.research.phase17c.metrics import summarize_returns
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _year_mask(frame: pd.DataFrame, year: int) -> pd.Series:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    return ts.dt.year == year


def _engine_year_stats_batch(
    frame: pd.DataFrame,
    *,
    probs_fn,
    year: int,
    stride: int = 15,
) -> dict[str, Any]:
    mask = _year_mask(frame, year)
    subset = frame.loc[mask].iloc[:: max(1, stride)].reset_index(drop=True)
    if subset.empty:
        return {
            "year": year,
            "bars": 0,
            "trend_bars": 0,
            "trades": 0,
            "ceiling": 0.0,
            "mean_prob": 0.0,
            "pf": 0.0,
            "expectancy": 0.0,
            "trend_contribution": 0,
        }

    regimes = [rule_classify_row(subset.iloc[i]) for i in range(len(subset))]
    trend_idx = [i for i, r in enumerate(regimes) if r == "TREND"]
    if not trend_idx:
        return {
            "year": year,
            "bars": len(subset),
            "trend_bars": 0,
            "trades": 0,
            "ceiling": 0.0,
            "mean_prob": 0.0,
            "pf": 0.0,
            "expectancy": 0.0,
            "trend_contribution": 0,
        }

    trend_frame = subset.iloc[trend_idx]
    all_probs = probs_fn(trend_frame)
    probs: list[float] = []
    returns: list[float] = []
    for j, i in enumerate(trend_idx):
        row = subset.iloc[i]
        rule = evaluate_variant_a(row, regime="TREND")
        prob = float(all_probs[j])
        probs.append(prob)
        if rule in ("BUY", "SELL") and prob >= RF_THRESHOLD:
            returns.append(prob - RF_THRESHOLD)

    perf = summarize_returns(returns)
    return {
        "year": year,
        "bars": len(subset),
        "trend_bars": len(trend_idx),
        "trades": perf["trades"],
        "ceiling": round(float(max(probs)), 6) if probs else 0.0,
        "mean_prob": round(float(np.mean(probs)), 6) if probs else 0.0,
        "std_prob": round(float(np.std(probs)), 6) if probs else 0.0,
        "pf": perf["pf"],
        "expectancy": perf["expectancy"],
        "drawdown": perf["drawdown"],
        "win_rate": perf["win_rate"],
        "trend_contribution": perf["trades"],
        "confidence_distribution": {
            "p50": round(float(np.percentile(probs, 50)), 6) if probs else 0.0,
            "p95": round(float(np.percentile(probs, 95)), 6) if probs else 0.0,
        },
    }


def run_walk_forward(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    bundle: TrendRfBundle,
    research: ResearchRfModel,
    *,
    years: tuple[int, ...] = WALK_FORWARD_YEARS,
    stride: int = 15,
) -> dict[str, Any]:
    # Limit to walk-forward span (≈6y) — chronological, no shuffle.
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles

    window = prepare_calibration_candles(candles, days=365 * 6 + 30)
    unified = build_unified_frame(window, dataset)
    unified_r = attach_top5_features(unified)

    frozen_order = list(bundle.feature_order)
    research_order = list(research.feature_order)

    def frozen_batch(frame: pd.DataFrame) -> np.ndarray:
        X = frame.reindex(columns=frozen_order).astype(float).fillna(0.0).values
        Xs = bundle.scaler.transform(X)
        return bundle.model.predict_proba(Xs)[:, 1]

    def research_batch(frame: pd.DataFrame) -> np.ndarray:
        X = frame.reindex(columns=research_order).astype(float).fillna(0.0).values
        Xs = research.scaler.transform(X)
        return research.model.predict_proba(Xs)[:, 1]

    frozen_years = []
    research_years = []
    for year in years:
        print(f"phase17c: walk-forward {year} ...", flush=True)
        frozen_years.append(
            _engine_year_stats_batch(unified, probs_fn=frozen_batch, year=year, stride=stride)
        )
        research_years.append(
            _engine_year_stats_batch(unified_r, probs_fn=research_batch, year=year, stride=stride)
        )

    # Stability: coefficient of variation of PF across years with trades.
    def _pf_cv(rows: list[dict[str, Any]]) -> float:
        pfs = [r["pf"] for r in rows if r["trades"] > 0]
        if len(pfs) < 2:
            return 0.0
        mean = float(np.mean(pfs))
        if mean < 1e-12:
            return 0.0
        return round(float(np.std(pfs) / mean), 6)

    research_improved_years = sum(
        1 for f, r in zip(frozen_years, research_years)
        if r["trades"] >= f["trades"] and r["ceiling"] >= f["ceiling"]
    )
    active_years = sum(1 for r in research_years if r["trend_bars"] > 0)

    return {
        "phase": "17C",
        "years": list(years),
        "frozen": frozen_years,
        "research": research_years,
        "stability": {
            "frozen_pf_cv": _pf_cv(frozen_years),
            "research_pf_cv": _pf_cv(research_years),
            "years_research_not_worse": research_improved_years,
            "active_years": active_years,
            "walk_forward_stable": (
                active_years > 0
                and research_improved_years >= max(1, active_years // 2)
                and _pf_cv(research_years) < 2.0
            ),
        },
    }
