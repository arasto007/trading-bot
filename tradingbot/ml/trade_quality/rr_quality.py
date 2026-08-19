"""Phase 14.3 — risk-reward ratio quality."""

from __future__ import annotations

VOL_REGIME_ENGINE = "vol_regime"
VOL_REGIME_RR_MIN = 0.8
VOL_REGIME_RR_MAX = 1.5


def _vol_regime_rr_score(rr: float) -> tuple[float, str]:
    if rr < VOL_REGIME_RR_MIN:
        return 0.0, f"RR {rr:.2f} below vol_regime research floor {VOL_REGIME_RR_MIN}"
    if rr <= 1.0:
        return 0.85, f"RR {rr:.2f} vol_regime research band (0.8-1.0)"
    if rr <= VOL_REGIME_RR_MAX:
        return 0.90, f"RR {rr:.2f} vol_regime upper research band (1.0-1.5)"
    if rr < 2.0:
        return 0.95, f"RR {rr:.2f} vol_regime transition band (1.5-2.0)"
    return 1.0, f"RR {rr:.2f} meets production minimum 1:2"


def rr_quality_score(rr_ratio: float, *, engine_id: str | None = None) -> tuple[float, str]:
    rr = float(rr_ratio)
    if engine_id == VOL_REGIME_ENGINE:
        return _vol_regime_rr_score(rr)
    if rr < 1.5:
        return 0.0, f"RR {rr:.2f} below 1.5"
    if rr < 2.0:
        return 0.6, f"RR {rr:.2f} in 1.5-2.0 band"
    return 1.0, f"RR {rr:.2f} meets minimum 1:2"
