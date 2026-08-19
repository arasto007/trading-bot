"""Phase 14.9 — dynamic engine weighting (research-only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


@dataclass(frozen=True)
class EngineWeights:
    trend_weight: float
    range_weight: float
    regime: str
    factors: dict[str, float]

    def selected_engine(self) -> str | None:
        if self.regime in ("HIGH_VOLATILITY", "NO_TRADE"):
            return None
        if self.trend_weight >= self.range_weight and self.trend_weight >= 0.45:
            return "trend_rf_v40"
        if self.range_weight > self.trend_weight and self.range_weight >= 0.45:
            return "phase9_9"
        if self.regime == "TREND":
            return "trend_rf_v40"
        if self.regime == "RANGE":
            return "phase9_9"
        return None


def compute_trend_weight(row: pd.Series | dict[str, Any], *, regime: str) -> tuple[float, dict[str, float]]:
    feats = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    adx = float(feats.get("adx", feats.get("trend_strength", 20.0)))
    ema_slope = abs(float(feats.get("ema50_slope", 0.0)))
    atr_pct = float(feats.get("atr_percentile", feats.get("volatility", 50.0)))

    adx_part = _clamp(adx / 35.0)
    slope_part = _clamp(ema_slope / 0.25)
    vol_part = _clamp(atr_pct / 80.0) * 0.3
    regime_boost = 0.15 if str(regime).upper() == "TREND" else 0.0

    weight = _clamp(0.35 * adx_part + 0.40 * slope_part + 0.15 * vol_part + regime_boost)
    return round(weight, 4), {"adx": adx_part, "ema_slope": slope_part, "volatility": vol_part}


def compute_range_weight(row: pd.Series | dict[str, Any], *, regime: str) -> tuple[float, dict[str, float]]:
    feats = row.to_dict() if hasattr(row, "to_dict") else dict(row)
    adx = float(feats.get("adx", feats.get("trend_strength", 20.0)))
    atr_pct = float(feats.get("atr_percentile", feats.get("volatility", 50.0)))
    structure = abs(float(feats.get("structure_distance", 0.0)))

    adx_low = _clamp((25.0 - adx) / 25.0) if adx < 25.0 else 0.2
    atr_compress = _clamp((40.0 - atr_pct) / 40.0) if atr_pct < 40.0 else 0.15
    mean_rev = _clamp(structure / 2.0) if structure < 2.0 else 0.3
    regime_boost = 0.15 if str(regime).upper() == "RANGE" else 0.0

    weight = _clamp(0.40 * adx_low + 0.30 * atr_compress + 0.20 * mean_rev + regime_boost)
    return round(weight, 4), {"adx_low": adx_low, "atr_compression": atr_compress, "mean_reversion": mean_rev}


def compute_engine_weights(row: pd.Series | dict[str, Any], *, regime: str) -> EngineWeights:
    tw, tf = compute_trend_weight(row, regime=regime)
    rw, rf = compute_range_weight(row, regime=regime)
    total = tw + rw
    if total > 0:
        tw, rw = tw / total, rw / total
    return EngineWeights(
        trend_weight=round(tw, 4),
        range_weight=round(rw, 4),
        regime=str(regime).upper(),
        factors={"trend": tf, "range": rf},
    )
