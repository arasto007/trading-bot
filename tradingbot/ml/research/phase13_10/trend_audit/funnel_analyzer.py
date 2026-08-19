"""Phase 13.10 — trend signal contribution funnel audit."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.router_optimizer.trade_filter_optimizer import resolve_routing_action
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter


def audit_trend_funnel(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    rule_fn: Callable[..., str],
    model: Any = None,
    scaler: Any = None,
    model_name: str = "random_forest",
    threshold: float = 0.45,
    policy: str = "A",
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    """Trace TREND candle funnel through rules, ML, confidence, and router."""
    unified = build_unified_frame(candles, dataset)
    regimes = rule_classify(unified)

    trend_candles = 0
    rule_signals = 0
    ml_accepted = 0
    confidence_accepted = 0
    router_accepted = 0
    routed_to_trend = 0
    rejection_reasons: Counter[str] = Counter()

    for i in range(len(unified)):
        row = unified.iloc[i]
        regime = str(regimes.iloc[i])
        if regime != "TREND":
            continue
        trend_candles += 1

        direction = rule_fn(row, regime="TREND")
        if direction not in ("BUY", "SELL"):
            rejection_reasons["no_rule_signal"] += 1
            continue
        rule_signals += 1

        action = resolve_routing_action(regime, policy)
        if action != "TREND":
            rejection_reasons["router_policy_block"] += 1
            continue
        routed_to_trend += 1

        if model is None or scaler is None:
            ml_out = {"allow_trade": True, "probability": 1.0, "confidence": 1.0}
        else:
            ml_out = apply_trend_ml_filter(
                row, model=model, scaler=scaler, model_name=model_name, threshold=threshold
            )
        if not ml_out["allow_trade"]:
            rejection_reasons["ml_filter"] += 1
            continue
        ml_accepted += 1

        conf = float(ml_out.get("confidence", 0.0))
        if min_confidence > 0 and conf < min_confidence:
            rejection_reasons["confidence_filter"] += 1
            continue
        confidence_accepted += 1
        router_accepted += 1

    stages = [
        {"stage": "TREND_candles", "count": trend_candles},
        {"stage": "rule_signals", "count": rule_signals},
        {"stage": "ml_accepted", "count": ml_accepted},
        {"stage": "confidence_accepted", "count": confidence_accepted},
        {"stage": "router_accepted_trades", "count": router_accepted},
    ]
    funnel_chain = " -> ".join(str(s["count"]) for s in stages)

    bottlenecks: list[str] = []
    if trend_candles == 0:
        bottlenecks.append("No TREND regime candles")
    elif rule_signals == 0:
        bottlenecks.append("Rules never fire on TREND candles")
    elif ml_accepted < rule_signals * 0.1:
        bottlenecks.append("ML filter blocks >90% of rule signals")
    elif confidence_accepted < ml_accepted:
        bottlenecks.append("Confidence filter reduces ML-accepted signals")
    elif router_accepted < confidence_accepted:
        bottlenecks.append("Router policy blocks trend path")

    primary_bottleneck = bottlenecks[0] if bottlenecks else "none"

    return {
        "phase": "13.10",
        "funnel": {
            "stages": stages,
            "funnel_chain": funnel_chain,
            "trend_candles": trend_candles,
            "rule_signals": rule_signals,
            "ml_accepted": ml_accepted,
            "confidence_accepted": confidence_accepted,
            "router_accepted": router_accepted,
            "routed_to_trend_engine": routed_to_trend,
        },
        "rejection_reasons": dict(rejection_reasons),
        "bottlenecks": bottlenecks,
        "primary_bottleneck": primary_bottleneck,
        "policy": policy,
        "ml_threshold": threshold,
        "regime_distribution": {str(k): int(v) for k, v in regimes.value_counts().to_dict().items()},
        "summary": (
            f"TREND candles={trend_candles} -> rules={rule_signals} -> "
            f"ML={ml_accepted} -> confidence={confidence_accepted} -> router={router_accepted}"
        ),
    }
