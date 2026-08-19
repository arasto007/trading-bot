"""Phase 11.5 — SELL bias root-cause analysis."""

from __future__ import annotations

from typing import Any

import numpy as np


def analyze_sell_bias(
    trades: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
) -> dict[str, Any]:
    probs = [float(c["ml_probability"]) for c in cycles if c.get("ml_probability") is not None]
    sell_probs = [p for p in probs if p <= 0.45]
    buy_probs = [p for p in probs if p >= 0.55]

    sell_trades = [t for t in trades if t.get("direction") == "SELL"]
    buy_trades = [t for t in trades if t.get("direction") == "BUY"]
    sell_ratio = len(sell_trades) / max(1, len(sell_trades) + len(buy_trades))

    ml_sell_cycles = sum(1 for c in cycles if c.get("ml_signal") == "SELL")
    ml_buy_cycles = sum(1 for c in cycles if c.get("ml_signal") == "BUY")
    ml_hold_cycles = sum(1 for c in cycles if c.get("ml_signal") == "HOLD")

    # Market proxy: net candle direction from cycles with kernel signals
    bearish_signals = sum(1 for c in cycles if c.get("kernel_signal") == "SELL")
    bullish_signals = sum(1 for c in cycles if c.get("kernel_signal") == "BUY")

    calibration_ok = len(sell_probs) > 0 and np.mean(sell_probs) < 0.45
    root_causes: list[str] = []
    if sell_ratio > 0.7:
        root_causes.append("high_sell_trade_ratio")
    if ml_sell_cycles > ml_buy_cycles * 5:
        root_causes.append("model_emits_more_sell_signals")
    if bearish_signals > bullish_signals * 2:
        root_causes.append("legacy_strategy_also_bearish")
    if len(buy_probs) < len(sell_probs) * 0.1:
        root_causes.append("few_buy_probability_events")

    verdict = (
        "threshold_and_market_regime"
        if "model_emits_more_sell_signals" in root_causes
        else "calibration_issue"
        if not calibration_ok
        else "mixed"
    )

    return {
        "sell_trades_pct": round(sell_ratio, 4),
        "buy_trades": len(buy_trades),
        "sell_trades": len(sell_trades),
        "ml_cycles": {"buy": ml_buy_cycles, "sell": ml_sell_cycles, "hold": ml_hold_cycles},
        "probability_distribution": {
            "mean": round(float(np.mean(probs)), 4) if probs else None,
            "std": round(float(np.std(probs)), 4) if probs else None,
            "p25": round(float(np.percentile(probs, 25)), 4) if probs else None,
            "p50": round(float(np.percentile(probs, 50)), 4) if probs else None,
            "p75": round(float(np.percentile(probs, 75)), 4) if probs else None,
            "sell_bucket_mean": round(float(np.mean(sell_probs)), 4) if sell_probs else None,
            "buy_bucket_mean": round(float(np.mean(buy_probs)), 4) if buy_probs else None,
        },
        "buy_opportunity_loss": {
            "cycles_near_buy_threshold": sum(1 for p in probs if 0.50 <= p < 0.55),
            "cycles_near_sell_threshold": sum(1 for p in probs if 0.45 < p <= 0.50),
        },
        "market_context": {
            "kernel_sell_signals": bearish_signals,
            "kernel_buy_signals": bullish_signals,
        },
        "root_causes": root_causes,
        "verdict": verdict,
        "is_calibration_bug": verdict == "calibration_issue",
        "is_market_bearish": bearish_signals > bullish_signals,
    }
