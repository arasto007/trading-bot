"""Phase 13.5 — Phase 13.3 trend strategy + Phase 13.4 ML filter adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import phase13_4_reports_dir
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features
from tradingbot.ml.research.trend_ml.label_builder import build_supervised_labels
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model
from tradingbot.ml.research.trend_ml.trend_ml_filter import DEFAULT_THRESHOLD, apply_trend_ml_filter
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules
from tradingbot.ml.research.trend_strategy.trend_signal import build_trend_signal


class TrendEngineAdapter:
    """Phase 13.3 rules gated by Phase 13.4 ML probability filter."""

    def __init__(
        self,
        *,
        model: Any,
        scaler: StandardScaler,
        model_name: str,
        threshold: float = DEFAULT_THRESHOLD,
        symbol: str = "XAUUSD",
    ) -> None:
        self.model = model
        self.scaler = scaler
        self.model_name = model_name
        self.threshold = threshold
        self.symbol = symbol.upper()
        self.model_version = f"phase13_4_trend_ml_{model_name}"

    @classmethod
    def load(
        cls,
        candles: pd.DataFrame,
        *,
        symbol: str = "XAUUSD",
        base_dir: str | Path | None = None,
        seed: int = 42,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> "TrendEngineAdapter":
        model_name, threshold = _resolve_trend_ml_spec(base_dir, threshold)
        frame = build_ml_features(candles)
        samples = build_supervised_labels(frame, symbol=symbol)
        if samples.empty:
            model = create_trend_ml_model(model_name, seed=seed)
            scaler = StandardScaler()
            return cls(model=model, scaler=scaler, model_name=model_name, threshold=threshold, symbol=symbol)

        cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in samples.columns]
        ordered = samples.sort_values("timestamp")
        X = ordered[cols].astype(float)
        y = ordered["successful_trade"].astype(int).values
        scaler = StandardScaler()
        X_s = scaler.fit_transform(X)
        model = create_trend_ml_model(model_name, seed=seed)
        model.fit(X_s, y)
        return cls(model=model, scaler=scaler, model_name=model_name, threshold=threshold, symbol=symbol)

    def evaluate(self, row: pd.Series, *, regime: str) -> dict[str, Any]:
        direction = evaluate_trend_rules(row, regime=regime)
        if direction == "HOLD" or regime != "TREND":
            return {
                "signal": "HOLD",
                "probability": 0.0,
                "confidence": 0.0,
                "model_version": self.model_version,
                "regime": regime,
                "engine": "trend_ml",
                "allow_trade": False,
            }

        ml = apply_trend_ml_filter(
            row,
            model=self.model,
            scaler=self.scaler,
            model_name=self.model_name,
            threshold=self.threshold,
        )
        signal = direction if ml["allow_trade"] else "HOLD"
        trend_sig = build_trend_signal(row, symbol=self.symbol, direction=direction)
        return {
            "signal": signal,
            "probability": ml["probability"],
            "confidence": ml["confidence"],
            "model_version": ml["model_version"],
            "regime": "TREND",
            "engine": "trend_ml",
            "allow_trade": ml["allow_trade"],
            "entry": trend_sig.get("entry"),
            "sl": trend_sig.get("stop_loss"),
            "tp": trend_sig.get("take_profit"),
            "risk_pct": trend_sig.get("risk_percent"),
        }


def _resolve_trend_ml_spec(base_dir: str | Path | None, default_threshold: float) -> tuple[str, float]:
    for root in (base_dir, None):
        path = phase13_4_reports_dir(root) / "trend_ml_best_model.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return str(payload.get("model", "logistic")), float(payload.get("threshold", default_threshold))
    return "logistic", default_threshold
