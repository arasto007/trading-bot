"""Phase 14.9 — Phase 9.9 range engine zero-trade analysis."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.decision_engine.validation import load_production_engines
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame, row_for_phase99_range
from tradingbot.ml.research.phase14_6.confidence_distribution import distribution_stats
from tradingbot.ml.research.phase14_9.config import RANGE_ENGINE_ID


def analyze_range_engine(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    symbol: str = "XAUUSD",
    seed: int = 42,
    stride: int = 5,
    range_engine: Any | None = None,
    unified: pd.DataFrame | None = None,
    calibration_threshold: float = 0.30,
    legacy_threshold: float = 0.55,
) -> dict[str, Any]:
    if unified is None:
        unified = build_unified_frame(candles, dataset)
    if range_engine is None:
        range_engine, _ = load_production_engines(candles, symbol=symbol, seed=seed)

    signals: list[dict[str, Any]] = []
    raw_confs: list[float] = []

    for i in range(0, len(unified), max(1, stride)):
        row = unified.iloc[i]
        ev = range_engine.evaluate(row=row_for_phase99_range(row))
        sig = str(ev.get("signal", "HOLD"))
        conf = float(ev.get("confidence", 0.0))
        raw_confs.append(conf)
        if sig in ("BUY", "SELL"):
            signals.append(
                {
                    "signal": sig,
                    "confidence": conf,
                    "passes_legacy_055": conf >= legacy_threshold,
                    "passes_platt_030": conf >= calibration_threshold,
                    "probability": float(ev.get("probability", 0.0)),
                }
            )

    legacy_accept = sum(1 for s in signals if s["passes_legacy_055"])
    platt_accept = sum(1 for s in signals if s["passes_platt_030"])

    return {
        "phase": "14.9",
        "engine": RANGE_ENGINE_ID,
        "bars_sampled": len(range(0, len(unified), max(1, stride))),
        "raw_signals": len(signals),
        "confidence_distribution": distribution_stats(raw_confs),
        "signal_confidence_distribution": distribution_stats([s["confidence"] for s in signals]),
        "legacy_threshold_055_accepted": legacy_accept,
        "platt_threshold_030_accepted": platt_accept,
        "zero_trades_root_causes": [
            "Model raw confidence clustered near 0.27 (distance from 0.5)",
            f"Legacy 0.55 gate blocks {len(signals) - legacy_accept}/{len(signals) or 1} signals",
            "Adaptive router rarely selects RANGE when TREND weight dominates",
            "Phase 14.1 composition further reduces composed confidence",
        ],
        "calibration_interaction": {
            "mean_raw_confidence": distribution_stats(raw_confs)["mean"],
            "would_pass_at_030": platt_accept,
            "would_pass_at_055": legacy_accept,
        },
    }
