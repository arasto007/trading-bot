"""Phase 11A research adapter — institutional feature store + regime models (NO LIVE ENABLE)."""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.domain.market_filters import compute_adx
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.domain.enums import SignalDirection
from tradingbot.ml.feature_store import InstitutionalFeatureStore, classify_regime

_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "ml" / "research" / "phase11a" / "models"


@dataclass
class InstitutionalPrediction:
    direction: str
    probability: float
    confidence: float
    regime: str
    model_type: str
    top_features: list[dict[str, float]]


def _load_best_artifact(model_dir: Path | None = None) -> dict[str, Any] | None:
    root = model_dir or _DEFAULT_MODEL_DIR
    if not root.is_dir():
        return None
    best_path: Path | None = None
    best_rank = (-1.0, -1.0)
    for path in root.glob("*_*.pkl"):
        try:
            art = pickle.loads(path.read_bytes())
        except Exception:
            continue
        m = art.get("metrics") or {}
        rank = (float(m.get("oos_pf", 0)), float(m.get("oos_expectancy_r", 0)))
        if rank > best_rank:
            best_rank = rank
            best_path = path
    if best_path is None:
        return None
    return pickle.loads(best_path.read_bytes())


class InstitutionalResearchAdapter:
    """Research-only ML confirmation using Phase 11A store (shadow / replay only)."""

    def __init__(
        self,
        *,
        model_dir: Path | None = None,
        threshold: float = 0.52,
        artifact: dict[str, Any] | None = None,
    ) -> None:
        self._artifact = artifact or _load_best_artifact(model_dir)
        self._threshold = threshold

    @property
    def ready(self) -> bool:
        return self._artifact is not None and "model" in self._artifact

    def predict_at(self, df: pd.DataFrame, index: int) -> InstitutionalPrediction | None:
        if not self.ready:
            return None
        model = self._artifact["model"]
        features: list[str] = self._artifact["features"]
        regime_name = self._artifact.get("regime", "TREND")

        feats = InstitutionalFeatureStore.compute_at(df, index)
        adx = compute_adx(df.iloc[: index + 1])
        live_regime = classify_regime(adx=adx, atr_pct=float(feats["atr_pct"]))
        x = np.array([[feats.get(f, 0.0) for f in features]], dtype=float)
        prob = float(model.predict_proba(x)[0, 1])

        contribs: list[dict[str, float]] = []
        if hasattr(model, "feature_importances_"):
            imp = model.feature_importances_
            pairs = sorted(zip(features, imp * x.flatten()), key=lambda t: abs(t[1]), reverse=True)[:5]
            contribs = [{"feature": f, "contribution": round(float(v), 6)} for f, v in pairs]

        direction = "BUY" if prob >= self._threshold else "SELL" if prob <= (1 - self._threshold) else "HOLD"
        return InstitutionalPrediction(
            direction=direction,
            probability=round(prob, 4),
            confidence=round(abs(prob - 0.5) * 2, 4),
            regime=live_regime or regime_name,
            model_type=str(self._artifact.get("model_type", "unknown")),
            top_features=contribs,
        )

    def generate_signal(self, market: MarketKey, df: pd.DataFrame) -> TradingSignal | None:
        if df is None or df.empty:
            return None
        pred = self.predict_at(df, len(df) - 1)
        if pred is None or pred.direction == "HOLD":
            return None
        direction = SignalDirection.BUY if pred.direction == "BUY" else SignalDirection.SELL
        return TradingSignal(
            direction=direction,
            confidence=pred.confidence,
            symbol=market.symbol,
            timeframe=market.timeframe,
            strategy_name="institutional_research_ml",
            metadata={
                "ml_probability": pred.probability,
                "regime": pred.regime,
                "model_type": pred.model_type,
                "top_features": pred.top_features,
                "research_only": True,
            },
        )
