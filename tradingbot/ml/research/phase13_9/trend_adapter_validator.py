"""Phase 13.9 — verify Phase 13.3 trend signal preservation on unified frame."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_9.config import MIN_SIGNALS_TARGET
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules


def count_trend_rule_signals(frame: pd.DataFrame) -> dict[str, Any]:
    regimes = attach_regime_labels(frame)
    trend_candles = rule_signals = 0
    for i in range(len(frame)):
        if str(regimes.iloc[i]) != "TREND":
            continue
        trend_candles += 1
        if evaluate_trend_rules(frame.iloc[i], regime="TREND") in ("BUY", "SELL"):
            rule_signals += 1
    return {
        "trend_candles": trend_candles,
        "rule_signals": rule_signals,
        "signal_rate": round(rule_signals / max(trend_candles, 1), 4),
    }


def validate_trend_adapter(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
) -> dict[str, Any]:
    canonical = build_ml_features(candles)
    unified = build_unified_frame(candles, dataset)
    canon_stats = count_trend_rule_signals(canonical)
    unified_stats = count_trend_rule_signals(unified)

    parity = abs(canon_stats["rule_signals"] - unified_stats["rule_signals"]) <= max(
        5, int(canon_stats["rule_signals"] * 0.01)
    )
    preserved = unified_stats["rule_signals"] >= MIN_SIGNALS_TARGET

    return {
        "phase": "13.9",
        "canonical": canon_stats,
        "unified": unified_stats,
        "signals_preserved": preserved,
        "parity_with_phase13_3": parity,
        "delta_signals": unified_stats["rule_signals"] - canon_stats["rule_signals"],
        "pass": parity and preserved,
    }
