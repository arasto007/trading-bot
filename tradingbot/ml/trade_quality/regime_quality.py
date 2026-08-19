"""Phase 14.3 — engine/regime compatibility scoring."""

from __future__ import annotations

RANGE_ENGINE = "phase9_9"
TREND_ENGINE = "trend_rf_v40"
TREND_ENGINE_V41 = "trend_rf_v41"
VOL_REGIME_ENGINE = "vol_regime"

_TREND_MATRIX: dict[str, float] = {
    "TREND": 1.0,
    "RANGE": 0.4,
    "HIGH_VOLATILITY": 0.0,
    "NO_TRADE": 0.0,
}

_RANGE_MATRIX: dict[str, float] = {
    "RANGE": 1.0,
    "TREND": 0.5,
    "HIGH_VOLATILITY": 0.0,
    "NO_TRADE": 0.0,
}

_VOL_REGIME_MATRIX: dict[str, float] = {
    "TREND": 1.0,
    "RANGE": 0.85,
    "HIGH_VOLATILITY": 1.0,
    "NO_TRADE": 0.0,
}


def regime_quality_score(engine: str | None, regime: str) -> tuple[float, str]:
    regime = str(regime).upper()
    engine = str(engine or "")
    if engine in (TREND_ENGINE, TREND_ENGINE_V41):
        score = _TREND_MATRIX.get(regime, 0.0)
        return score, f"trend engine in {regime} → {score}"
    if engine == RANGE_ENGINE:
        score = _RANGE_MATRIX.get(regime, 0.0)
        return score, f"range engine in {regime} → {score}"
    if engine == VOL_REGIME_ENGINE:
        score = _VOL_REGIME_MATRIX.get(regime, 0.0)
        return score, f"vol_regime engine in {regime} → {score}"
    return 0.0, "unknown engine — zero regime quality"
