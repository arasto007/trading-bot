"""Phase 13.8 — recovered trend engine for router simulation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import pandas as pd

from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal

if TYPE_CHECKING:
    from tradingbot.ml.feature_alignment.distribution_aligner import DistributionAligner


class RecoveredTrendEngine:
    """Research-only trend adapter using Phase 13.8 recovered rules + ML."""

    def __init__(
        self,
        *,
        model: Any,
        scaler: Any,
        model_name: str,
        threshold: float,
        rule_fn: Callable[..., str],
        symbol: str = "XAUUSD",
        aligner: Any | None = None,
    ) -> None:
        self.model = model
        self.scaler = scaler
        self.model_name = model_name
        self.threshold = threshold
        self.rule_fn = rule_fn
        self.symbol = symbol
        self.aligner = aligner
        self.model_version = f"phase13_8_{model_name}"
        self.engine = "trend_ml"

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
        ml_row = self.aligner.align_row(row) if self.aligner is not None else row
        ml = apply_trend_ml_filter(
            ml_row, model=self.model, scaler=self.scaler, model_name=self.model_name, threshold=self.threshold
        )
        signal = direction if ml["allow_trade"] else "HOLD"
        trend_sig = build_trend_signal(row, symbol=self.symbol, direction=direction)
        return {
            "signal": signal,
            "probability": ml["probability"],
            "confidence": ml["confidence"],
            "engine": "trend_ml",
            "allow_trade": ml["allow_trade"],
            "regime": "TREND",
            "model_version": self.model_version,
            "entry": trend_sig.get("entry"),
            "sl": trend_sig.get("stop_loss"),
            "tp": trend_sig.get("take_profit"),
            "risk_pct": trend_sig.get("risk_percent"),
        }
