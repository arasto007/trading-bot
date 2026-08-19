"""Phase 15I — Phase 9.9 signal audit without router."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range
from tradingbot.ml.research.phase15i.config import RANGE_ENGINE_ID


def audit_phase99_signals(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    stride: int = 15,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_inner = getattr(registry.get(RANGE_ENGINE_ID), "inner", None)

    counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    confidences: list[float] = []
    probabilities: list[float] = []
    wins = 0
    losses = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ev = range_inner.evaluate(row=row_for_phase99_range(row))
        sig = str(ev.get("signal", "HOLD"))
        counts[sig] = counts.get(sig, 0) + 1
        confidences.append(float(ev.get("confidence", 0.0)))
        probabilities.append(float(ev.get("probability", 0.5)))
        if sig in ("BUY", "SELL"):
            prob = float(ev.get("probability", 0.5))
            if (sig == "BUY" and prob >= 0.55) or (sig == "SELL" and prob <= 0.45):
                wins += 1
            else:
                losses += 1

    actionable = counts.get("BUY", 0) + counts.get("SELL", 0)
    total = sum(counts.values()) or 1
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    avg_prob = sum(probabilities) / len(probabilities) if probabilities else 0.5

    return {
        "phase": "15I",
        "engine": RANGE_ENGINE_ID,
        "without_router": True,
        "bars_evaluated": total,
        "signals": counts,
        "actionable_count": actionable,
        "actionable_rate": round(actionable / total, 4),
        "confidence": {
            "mean": round(avg_conf, 4),
            "min": round(min(confidences), 4) if confidences else 0.0,
            "max": round(max(confidences), 4) if confidences else 0.0,
        },
        "probability": {
            "mean": round(avg_prob, 4),
            "min": round(min(probabilities), 4) if probabilities else 0.0,
            "max": round(max(probabilities), 4) if probabilities else 0.0,
        },
        "threshold_aligned_signals": wins,
        "expectancy_proxy": round((wins - losses) / max(actionable, 1), 4),
        "profit_factor_proxy": round(wins / max(losses, 1), 4),
    }
