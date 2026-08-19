"""Phase 15G — frozen bundle vs research trend probability audit."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import TREND_MODEL_ID
from tradingbot.ml.decision_engine.validation import build_market_context, load_production_engines
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.phase15g.bundle_statistics import compare_distributions, distribution_stats, histogram


def _frozen_trend_engines(
    *,
    base_dir: str | None,
    symbol: str,
) -> tuple[Any, Any]:
    registry = EngineRegistry.build_default(
        base_dir=base_dir, build_trend_if_missing=False, symbol=symbol,
    )
    range_wrapped = registry.get("phase9_9")
    trend_wrapped = registry.get("trend_rf_v40")
    return (
        getattr(range_wrapped, "inner", None),
        getattr(trend_wrapped, "inner", None),
    )


def audit_bundle_probabilities(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    stride: int = 5,
    days: int = 180,
) -> dict[str, Any]:
    window = prepare_calibration_candles(candles, days=days)
    unified = build_unified_frame(window, dataset)

    frozen_range, frozen_trend = _frozen_trend_engines(base_dir=base_dir, symbol=symbol)
    research_range, research_trend = load_production_engines(window, symbol=symbol, seed=seed)

    frozen_probs: list[float] = []
    research_probs: list[float] = []
    frozen_signals: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
    research_signals: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
    trend_rows = 0

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        regime = str(row.get("regime", "RANGE"))
        if regime != "TREND":
            continue
        trend_rows += 1

        ctx_f = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=frozen_range, trend_engine=frozen_trend,
        )
        ctx_r = build_market_context(
            row, symbol=symbol, timeframe=timeframe,
            range_engine=research_range, trend_engine=research_trend,
        )

        fp = float(ctx_f.trend_signal.probability)
        rp = float(ctx_r.trend_signal.probability)
        frozen_probs.append(fp)
        research_probs.append(rp)
        fs = str(ctx_f.trend_signal.signal)
        rs = str(ctx_r.trend_signal.signal)
        frozen_signals[fs] = frozen_signals.get(fs, 0) + 1
        research_signals[rs] = research_signals.get(rs, 0) + 1

    comparison = compare_distributions(frozen_probs, research_probs)
    compressed = (
        comparison["frozen"]["max"] < comparison["research"]["p25"]
        if comparison["research"]["count"] > 0
        else False
    )

    return {
        "phase": "15G",
        "engine": TREND_MODEL_ID,
        "trend_bars_evaluated": trend_rows,
        "frozen_bundle": {
            "probabilities": distribution_stats(frozen_probs),
            "histogram": histogram(frozen_probs),
            "signals": frozen_signals,
        },
        "research_engine": {
            "probabilities": distribution_stats(research_probs),
            "histogram": histogram(research_probs),
            "signals": research_signals,
        },
        "comparison": comparison,
        "frozen_outputs_compressed": compressed,
        "diagnosis": (
            "Frozen bundle trend probabilities are compressed relative to research refit engine"
            if compressed
            else "Frozen bundle probability spread overlaps research engine"
        ),
    }
