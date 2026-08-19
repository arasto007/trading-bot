"""Phase 13.9 — signal loss funnel analyzer."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules


def _count_rule_signals(frame: pd.DataFrame, *, regimes: pd.Series) -> int:
    n = 0
    for i in range(len(frame)):
        if str(regimes.iloc[i]) != "TREND":
            continue
        if evaluate_trend_rules(frame.iloc[i], regime="TREND") in ("BUY", "SELL"):
            n += 1
    return n


def analyze_signal_loss(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    ml_model=None,
    ml_scaler=None,
    ml_threshold: float = 0.55,
    model_name: str = "logistic",
) -> dict[str, Any]:
    from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features

    canonical = build_ml_features(candles)
    legacy = prepare_merged_frame(candles, dataset)
    unified = build_unified_frame(candles, dataset)

    stages: list[dict[str, Any]] = []

    reg_canon = attach_regime_labels(canonical)
    sig_canon = _count_rule_signals(canonical, regimes=reg_canon)
    stages.append({"stage": "canonical_trend_frame", "rule_signals": sig_canon, "count": sig_canon})

    reg_legacy = rule_classify(legacy)
    sig_legacy = _count_rule_signals(legacy, regimes=reg_legacy)
    stages.append(
        {
            "stage": "legacy_router_merged",
            "rule_signals": sig_legacy,
            "count": sig_legacy,
            "drop_from_prior": sig_canon - sig_legacy,
            "cause": "dataset_overwrites_trend_ema50_slope",
        }
    )

    reg_unified = attach_regime_labels(unified)
    sig_unified = _count_rule_signals(unified, regimes=reg_unified)
    stages.append(
        {
            "stage": "unified_frame",
            "rule_signals": sig_unified,
            "count": sig_unified,
            "drop_from_prior": sig_legacy - sig_unified,
        }
    )

    ml_accepted = sig_unified
    if ml_model is not None and ml_scaler is not None:
        ml_accepted = 0
        for i in range(len(unified)):
            if str(reg_unified.iloc[i]) != "TREND":
                continue
            row = unified.iloc[i]
            if evaluate_trend_rules(row, regime="TREND") not in ("BUY", "SELL"):
                continue
            ml = apply_trend_ml_filter(
                row, model=ml_model, scaler=ml_scaler, model_name=model_name, threshold=ml_threshold
            )
            if ml["allow_trade"]:
                ml_accepted += 1
        stages.append(
            {
                "stage": "after_ml_filter",
                "count": ml_accepted,
                "drop_from_prior": sig_unified - ml_accepted,
                "threshold": ml_threshold,
            }
        )

    funnel_chain = " -> ".join(str(s["count"]) for s in stages)
    return {
        "phase": "13.9",
        "stages": stages,
        "funnel_chain": funnel_chain,
        "canonical_signals": sig_canon,
        "legacy_signals": sig_legacy,
        "unified_signals": sig_unified,
        "ml_accepted": ml_accepted,
        "signal_recovery": sig_unified >= 500,
        "example_trace": (
            f"{sig_canon} canonical -> {sig_legacy} legacy router "
            f"(dataset ema50_slope overwrite) -> {sig_unified} unified -> {ml_accepted} ML"
        ),
    }
