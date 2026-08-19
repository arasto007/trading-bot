"""Phase 16D — candidate feature catalog (evaluation only, not production)."""

from __future__ import annotations

from typing import Any

CANDIDATE_CATALOG: list[dict[str, Any]] = [
    {"id": "trend_persistence", "name": "Trend Persistence", "category": "duration",
     "description": "Consecutive bars with same rule direction signal"},
    {"id": "trend_age", "name": "Trend Age", "category": "duration",
     "description": "Bars since regime switched to TREND"},
    {"id": "momentum_acceleration", "name": "Momentum Acceleration", "category": "momentum",
     "description": "First derivative of candle momentum"},
    {"id": "slope_acceleration", "name": "Slope Acceleration", "category": "momentum",
     "description": "First derivative of EMA50 slope"},
    {"id": "atr_expansion_ratio", "name": "ATR Expansion Ratio", "category": "volatility",
     "description": "Current ATR vs rolling mean ATR"},
    {"id": "volume_expansion", "name": "Volume Expansion", "category": "volatility",
     "description": "Volume vs rolling mean volume (if available)"},
    {"id": "swing_efficiency", "name": "Swing Efficiency", "category": "structure",
     "description": "Price displacement per unit ATR over lookback"},
    {"id": "fractal_dimension_proxy", "name": "Fractal Dimension Proxy", "category": "structure",
     "description": "Path-length complexity proxy on close returns"},
    {"id": "hurst_proxy", "name": "Hurst Exponent Proxy", "category": "structure",
     "description": "Simplified R/S Hurst estimate on returns"},
    {"id": "adx_acceleration", "name": "ADX Acceleration", "category": "trend_strength",
     "description": "First derivative of ADX"},
    {"id": "mtf_agreement", "name": "Multi-Timeframe Agreement", "category": "alignment",
     "description": "Agreement of EMA20/50/200 alignment signs"},
    {"id": "ema_curvature", "name": "EMA Curvature", "category": "alignment",
     "description": "Second derivative of EMA20"},
    {"id": "macd_slope", "name": "MACD Slope", "category": "momentum",
     "description": "First derivative of MACD histogram"},
    {"id": "rsi_velocity", "name": "RSI Velocity", "category": "momentum",
     "description": "First derivative of RSI"},
    {"id": "breakout_quality", "name": "Breakout Quality", "category": "structure",
     "description": "Breakout distance weighted by ADX"},
    {"id": "distance_from_vwap_proxy", "name": "Distance From VWAP Proxy", "category": "price",
     "description": "Close distance from rolling VWAP proxy"},
]


def catalog_as_json() -> dict[str, Any]:
    return {
        "phase": "16D",
        "evaluation_only": True,
        "production_modified": False,
        "candidate_count": len(CANDIDATE_CATALOG),
        "candidates": CANDIDATE_CATALOG,
    }
