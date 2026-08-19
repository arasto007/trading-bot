"""Phase 17D — production trend_rf_v41 engine (RF + Top5)."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal


class TrendRfV41Engine:
    """
    Production v41 trend engine — mirrors RecoveredTrendEngine interface.
    Applies 16A aligner to base features, attaches Top5, then scores bundle.
    """

    def __init__(
        self,
        *,
        bundle: TrendRfBundle,
        threshold: float,
        rule_fn: Callable[..., str],
        symbol: str = "XAUUSD",
        aligner: Any | None = None,
        engine_id: str = "trend_rf_v41",
    ) -> None:
        self.bundle = bundle
        self.threshold = threshold
        self.rule_fn = rule_fn
        self.symbol = symbol
        self.aligner = aligner
        self.model_version = engine_id
        self.engine = engine_id

    def _enriched_row(self, row: pd.Series) -> pd.Series:
        missing = [f for f in self.bundle.feature_order if f not in row.index]
        if not missing:
            return row
        # Fallback must not use single-row Top5 — rolling features require full-frame attach (Phase 17B/22D).
        if self.aligner is not None:
            base = self.aligner.align_row(row)
            still_missing = [f for f in self.bundle.feature_order if f not in base.index]
            if not still_missing:
                return base
        raise ValueError(
            f"trend_rf_v41 missing features {missing} — PipelineCache must attach Top5 on unified frame"
        )

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
        enriched = self._enriched_row(row)
        prob = self.bundle.predict_proba(enriched)
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
