"""Phase 13.7 — trend routing funnel debugger."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.regime_router.trend_engine_adapter import TrendEngineAdapter
from tradingbot.ml.research.router_optimizer.optimizer_types import RegimeThresholdParams, classify_regimes
from tradingbot.ml.research.router_optimizer.trade_filter_optimizer import resolve_routing_action
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules


def debug_trend_routing(
    merged: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    trend_engine: TrendEngineAdapter,
    policy: str = "A",
    min_confidence: float = 0.0,
    use_phase132_classifier: bool = True,
) -> dict[str, Any]:
    """Trace why trend contribution may be zero inside the router."""
    if use_phase132_classifier:
        regimes = rule_classify(merged)
    else:
        regimes = classify_regimes(merged, RegimeThresholdParams())

    trend_candles = 0
    trend_rule_signals = 0
    ml_rejected = 0
    confidence_rejected = 0
    routed_to_trend = 0
    final_router_signals = 0
    funnel: list[dict[str, Any]] = []

    for i in range(len(merged)):
        row = merged.iloc[i]
        regime = str(regimes.iloc[i])
        if regime != "TREND":
            continue
        trend_candles += 1

        rule_dir = evaluate_trend_rules(row, regime="TREND")
        if rule_dir in ("BUY", "SELL"):
            trend_rule_signals += 1

        action = resolve_routing_action(regime, policy)
        if action != "TREND":
            continue
        routed_to_trend += 1

        out = trend_engine.evaluate(row, regime="TREND")
        if rule_dir in ("BUY", "SELL") and not out.get("allow_trade", False):
            ml_rejected += 1

        if out.get("signal") in ("BUY", "SELL"):
            conf = float(out.get("confidence", 0.0))
            if min_confidence > 0 and conf < min_confidence:
                confidence_rejected += 1
            else:
                final_router_signals += 1
                if len(funnel) < 25:
                    funnel.append(
                        {
                            "timestamp": str(row.get("timestamp")),
                            "rule_direction": rule_dir,
                            "ml_signal": out.get("signal"),
                            "probability": out.get("probability"),
                            "confidence": conf,
                            "allow_trade": out.get("allow_trade"),
                        }
                    )

    regime_counts = regimes.value_counts().to_dict()
    trend_pct = round(trend_candles / max(len(merged), 1) * 100, 2)

    answers = {
        "1_trend_candles": trend_candles,
        "2_trend_rule_signals": trend_rule_signals,
        "3_rejected_by_ml_filter": ml_rejected,
        "4_rejected_by_confidence": confidence_rejected,
        "5_reach_final_router": final_router_signals,
    }

    root_causes: list[str] = []
    if trend_candles == 0:
        root_causes.append("No bars classified as TREND by regime detector")
    elif trend_rule_signals == 0:
        root_causes.append("TREND bars exist but Phase 13.3 rules never fire")
    elif ml_rejected >= trend_rule_signals:
        root_causes.append("Phase 13.4 ML filter blocks most trend rule signals")
    if routed_to_trend == 0 and trend_candles > 0:
        root_causes.append(f"Routing policy '{policy}' never sends TREND bars to trend engine")

    return {
        "phase": "13.7",
        "regime_distribution": {str(k): int(v) for k, v in regime_counts.items()},
        "trend_candle_pct": trend_pct,
        "routed_to_trend_engine": routed_to_trend,
        "funnel_answers": answers,
        "sample_signals": funnel,
        "root_causes": root_causes,
        "summary": (
            f"Of {trend_candles} TREND candles: {trend_rule_signals} rule signals, "
            f"{ml_rejected} ML-blocked, {confidence_rejected} confidence-blocked, "
            f"{final_router_signals} reach router output."
        ),
    }
