"""Phase 17B — research trend engine for shadow replay (not production)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.phase17b.config import RF_THRESHOLD
from tradingbot.ml.research.phase17b.research_model import ResearchRfModel
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal


class ResearchTrendEngine:
    """
    Drop-in research adapter mimicking RecoveredTrendEngine interface.
    Uses ResearchRfModel only — does NOT touch production aligner or bundle.
    """

    def __init__(
        self,
        *,
        research_model: ResearchRfModel,
        threshold: float = RF_THRESHOLD,
        rule_fn: Callable[..., str],
        symbol: str = "XAUUSD",
    ) -> None:
        self.research_model = research_model
        self.threshold = threshold
        self.rule_fn = rule_fn
        self.symbol = symbol
        self.model_version = "phase17b_research_rf"
        self.engine = "trend_ml_research"
        self.aligner = None  # explicit: no 16A aligner on research path

    def _row_with_top5(self, row: pd.Series) -> pd.Series:
        if all(f in row.index for f in self.research_model.feature_order):
            return row
        frame = attach_top5_features(pd.DataFrame([row]))
        return frame.iloc[0]

    def evaluate(self, row: pd.Series, *, regime: str) -> dict[str, Any]:
        direction = self.rule_fn(row, regime=regime)
        if direction == "HOLD" or regime != "TREND":
            return {
                "signal": "HOLD",
                "probability": 0.0,
                "confidence": 0.0,
                "engine": self.engine,
                "allow_trade": False,
                "regime": regime,
                "model_version": self.model_version,
            }
        enriched = self._row_with_top5(row)
        prob = self.research_model.predict_proba(enriched)
        allow = prob >= self.threshold
        signal = direction if allow else "HOLD"
        trend_sig = build_trend_signal(row, symbol=self.symbol, direction=direction)
        confidence = min(1.0, max(0.0, abs(prob - 0.5) * 2.0))
        return {
            "signal": signal,
            "probability": prob,
            "confidence": confidence,
            "engine": self.engine,
            "allow_trade": allow,
            "regime": "TREND",
            "model_version": self.model_version,
            "entry": trend_sig.get("entry"),
            "sl": trend_sig.get("stop_loss"),
            "tp": trend_sig.get("take_profit"),
            "risk_pct": trend_sig.get("risk_percent"),
        }
