"""Phase 14.1 — final confidence composition."""

from __future__ import annotations

from tradingbot.ml.decision_engine.decision_types import MarketContext


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def compute_regime_strength(features: dict, regime: str) -> float:
    """Derive regime conviction from feature snapshot (0–1)."""
    regime = str(regime).upper()
    adx = float(features.get("adx", features.get("trend_strength", 0.0)))
    ema_slope = abs(float(features.get("ema50_slope", 0.0)))
    atr_pct = float(features.get("atr_percentile", 50.0))

    if regime == "TREND":
        adx_part = clamp(adx / 40.0)
        slope_part = clamp(ema_slope / 0.30)
        return clamp(0.6 * adx_part + 0.4 * slope_part)
    if regime == "RANGE":
        adx_part = clamp((25.0 - adx) / 25.0) if adx < 25.0 else 0.35
        vol_part = clamp((40.0 - atr_pct) / 40.0) if atr_pct < 40.0 else 0.35
        return clamp(0.55 * adx_part + 0.45 * vol_part)
    if regime == "HIGH_VOLATILITY":
        return clamp(atr_pct / 100.0, 0.1, 0.5)
    return 0.1


def compute_market_quality(context: MarketContext) -> float:
    """Market tradability score from volatility and spread (0–1)."""
    spread = float(context.features.get("spread_pips", 0.0))
    atr_pct = float(context.features.get("atr_percentile", context.volatility))
    vol_penalty = clamp(atr_pct / 95.0)
    quality = 1.0 - 0.45 * vol_penalty
    if spread >= 8.0:
        quality *= 0.5
    elif spread >= 4.0:
        quality *= 0.8
    if context.session in ("off_hours", "rollover"):
        quality *= 0.85
    return clamp(quality, 0.1, 1.0)


class ConfidenceEngine:
    """final_confidence = model_confidence * regime_strength * market_quality"""

    def compute(
        self,
        *,
        model_confidence: float,
        regime_strength: float,
        market_quality: float,
    ) -> float:
        raw = float(model_confidence) * float(regime_strength) * float(market_quality)
        return round(clamp(raw), 6)

    def from_context(self, context: MarketContext, model_confidence: float) -> float:
        regime_strength = context.regime_strength or compute_regime_strength(context.features, context.regime)
        market_quality = compute_market_quality(context)
        return self.compute(
            model_confidence=model_confidence,
            regime_strength=regime_strength,
            market_quality=market_quality,
        )

    def risk_hint(self, final_confidence: float, *, base_risk: float = 0.25) -> float:
        """Scaled risk suggestion — not executed in Phase 14.1."""
        return round(clamp(final_confidence * base_risk, 0.05, 0.35), 6)
