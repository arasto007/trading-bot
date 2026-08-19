"""Phase 13.10 — research trend engine wrappers (read-only on Phase 13.3/13.4)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal


class RulesOnlyTrendEngine:
    """Trend path without ML filter — rules-only signals in TREND regime."""

    def __init__(
        self,
        *,
        rule_fn: Callable[..., str],
        symbol: str = "XAUUSD",
    ) -> None:
        self.rule_fn = rule_fn
        self.symbol = symbol
        self.model_version = "phase13_10_rules_only"
        self.engine = "trend_ml"
        self.threshold = 0.0

    def evaluate(self, row: pd.Series, *, regime: str) -> dict[str, Any]:
        direction = self.rule_fn(row, regime=regime)
        if direction == "HOLD" or regime != "TREND":
            return {
                "signal": "HOLD",
                "probability": 0.0,
                "confidence": 0.0,
                "engine": "trend_ml",
                "allow_trade": False,
                "regime": regime,
                "model_version": self.model_version,
            }
        trend_sig = build_trend_signal(row, symbol=self.symbol, direction=direction)
        return {
            "signal": direction,
            "probability": 1.0,
            "confidence": 1.0,
            "engine": "trend_ml",
            "allow_trade": True,
            "regime": "TREND",
            "model_version": self.model_version,
            "entry": trend_sig.get("entry"),
            "sl": trend_sig.get("stop_loss"),
            "tp": trend_sig.get("take_profit"),
            "risk_pct": trend_sig.get("risk_percent"),
        }


def build_trend_adapter(
    *,
    model: Any,
    scaler: Any,
    model_name: str,
    threshold: float,
    rule_fn: Callable[..., str],
    symbol: str = "XAUUSD",
    rules_only: bool = False,
) -> RecoveredTrendEngine | RulesOnlyTrendEngine:
    if rules_only:
        return RulesOnlyTrendEngine(rule_fn=rule_fn, symbol=symbol)
    return RecoveredTrendEngine(
        model=model,
        scaler=scaler,
        model_name=model_name,
        threshold=threshold,
        rule_fn=rule_fn,
        symbol=symbol,
    )
