"""Phase 13.5 — Phase 9.9 range engine adapter (frozen artifacts, read-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.paper_trading.model_registry import Phase99Bundle, load_phase9_9_bundle
from tradingbot.ml.paper_trading.signal_engine import PaperSignal, SignalConfig, SignalEngine
from tradingbot.ml.research.regime_router.phase99_feature_validation import (
    hold_result_with_diagnostics,
    normalize_candles_for_builder,
    ordered_feature_vector,
    validate_runtime_feature_vector,
)
from tradingbot.ml.research.regime_router.unified_feature_input import resolve_range_features


class RangeEngineAdapter:
    """Wrap frozen Phase 9.9 model for RANGE regime signals."""

    def __init__(self, bundle: Phase99Bundle, *, symbol: str = "XAUUSD", base_dir: str | None = None) -> None:
        self.bundle = bundle
        self.symbol = symbol.upper()
        self.feature_builder = FeatureBuilder(symbol=symbol, base_dir=base_dir)
        cfg = bundle.config
        self.signal_engine = SignalEngine(
            SignalConfig(
                buy_threshold=float(cfg.get("buy_threshold", 0.55)),
                sell_threshold=float(cfg.get("sell_threshold", 0.45)),
            )
        )
        self.tp_r = float(cfg.get("tp_r", 2.0))
        self.sl_r = float(cfg.get("sl_r", 1.0))
        self.risk_pct = float(cfg.get("risk_pct", 0.005))
        self.model_version = "phase9_9_best"

    @classmethod
    def load(cls, *, symbol: str = "XAUUSD", base_dir: str | None = None) -> "RangeEngineAdapter":
        # Frozen Phase 9.9 artifacts always load from production path (read-only).
        bundle = load_phase9_9_bundle(base_dir=None, build_if_missing=False)
        return cls(bundle, symbol=symbol, base_dir=base_dir)

    def _features_from_row(self, row: pd.Series) -> dict[str, float] | None:
        cols = self.bundle.feature_order
        if all(c in row.index for c in cols):
            return {c: float(row[c]) for c in cols}
        return None

    def _features_from_candles(self, candles: pd.DataFrame, index: int) -> dict[str, float]:
        frame = normalize_candles_for_builder(candles)
        return self.feature_builder.compute_at(frame, index)

    def _resolve_features(
        self,
        *,
        row: pd.Series,
        candles: pd.DataFrame | None,
        bar_index: int | None,
    ) -> tuple[dict[str, float] | None, str | None]:
        feats, source, _errors = resolve_range_features(
            row=row,
            feature_order=list(self.bundle.feature_order),
            candles=candles,
            bar_index=bar_index,
            features_from_row=self._features_from_row,
            features_from_candles=self._features_from_candles,
        )
        return feats, source

    def evaluate(
        self,
        *,
        row: pd.Series,
        candles: pd.DataFrame | None = None,
        bar_index: int | None = None,
        atr: float | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        feats, feature_source = self._resolve_features(row=row, candles=candles, bar_index=bar_index)
        ok, errors = validate_runtime_feature_vector(feats, self.bundle.feature_order)
        if not ok:
            return hold_result_with_diagnostics(
                errors=errors,
                feature_source=feature_source,
                model_version=self.model_version,
            )

        ordered = ordered_feature_vector(feats or {}, self.bundle.feature_order)
        prob = self.bundle.predict_proba(ordered)
        signal = self.signal_engine.generate(prob).value
        confidence = abs(prob - 0.5) * 2.0
        entry = float(row.get("close", 0.0))
        atr_val = float(atr if atr is not None else row.get("atr_value", row.get("atr", 0.0)))
        if atr_val <= 0:
            atr_val = max(float(row.get("high", entry) - row.get("low", entry)), 0.01)

        sl_dist = atr_val * self.sl_r
        tp_dist = atr_val * self.tp_r
        if signal == PaperSignal.BUY.value:
            sl, tp = entry - sl_dist, entry + tp_dist
        elif signal == PaperSignal.SELL.value:
            sl, tp = entry + sl_dist, entry - tp_dist
        else:
            sl, tp = None, None

        return {
            "signal": signal,
            "probability": round(prob, 6),
            "confidence": round(confidence, 6),
            "sl": round(sl, 6) if sl is not None else None,
            "tp": round(tp, 6) if tp is not None else None,
            "model_version": self.model_version,
            "regime": "RANGE",
            "engine": "phase9_9",
            "entry": round(entry, 6),
            "risk_pct": self.risk_pct,
            "predict_proba_called": True,
            "feature_validation_failed": False,
            "feature_source": feature_source,
            "feature_vector": ordered,
            "timeframe": timeframe,
        }
