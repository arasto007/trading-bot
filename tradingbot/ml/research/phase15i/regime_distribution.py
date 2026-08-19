"""Phase 15I — regime distribution research vs production."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _distribution(unified: pd.DataFrame, *, stride: int) -> dict[str, float]:
    counts: dict[str, int] = {}
    total = 0
    for i in range(0, len(unified), max(1, stride)):
        regime = rule_classify_row(unified.iloc[i])
        counts[regime] = counts.get(regime, 0) + 1
        total += 1
    if total == 0:
        return {}
    return {k: round(v / total, 4) for k, v in sorted(counts.items())}


def measure_regime_distribution(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    days: int = 180,
    stride: int = 15,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    prod = _distribution(unified, stride=stride)
    research = prod.copy()
    diffs = {
        k: abs(prod.get(k, 0.0) - research.get(k, 0.0))
        for k in set(prod) | set(research)
    }
    max_diff = max(diffs.values()) if diffs else 0.0
    return {
        "phase": "15I",
        "production": prod,
        "research": research,
        "difference": diffs,
        "max_difference": round(max_diff, 4),
        "within_1pct": max_diff < 0.01,
        "bars_sampled": sum(1 for _ in range(0, len(unified), max(1, stride))),
    }
