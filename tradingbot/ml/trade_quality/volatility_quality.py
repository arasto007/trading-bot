"""Phase 14.3 — ATR percentile quality scoring."""

from __future__ import annotations


def volatility_quality_score(atr_percentile: float) -> tuple[float, str]:
    v = float(atr_percentile)
    # VOL_REGIME passes atr_pct as 0-1 fraction; legacy paths use 0-100 percentile.
    if 0.0 < v <= 1.0:
        v *= 100.0
    if v > 90.0:
        return 0.0, f"ATR {v:.0f} > 90 — reject"
    if v > 80.0:
        return 0.3, f"ATR {v:.0f} in 80-90 band"
    if v > 60.0:
        return 0.7, f"ATR {v:.0f} in 60-80 band"
    if v >= 20.0:
        return 1.0, f"ATR {v:.0f} in optimal 20-60 band"
    return 0.85, f"ATR {v:.0f} below 20 — slightly reduced"
