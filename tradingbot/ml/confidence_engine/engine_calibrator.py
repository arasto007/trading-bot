"""Phase 14.2A — engine-specific calibration factors."""

from __future__ import annotations

from tradingbot.ml.confidence_engine.calibration_policy import (
    PHASE99_VALIDATED_PF,
    RANGE_ENGINE_FACTOR_MAX,
    RANGE_ENGINE_FACTOR_MIN,
    TREND_ENGINE_FACTOR_MAX,
    TREND_ENGINE_FACTOR_MIN,
    TREND_RF_MONTE_CARLO,
    TREND_RF_VALIDATED_PF,
    TREND_RF_WF_ROBUSTNESS,
)

RANGE_MODEL_ID = "phase9_9"
TREND_MODEL_ID = "trend_rf_v40"


def engine_calibration_factor(*, engine: str | None, regime: str, regime_strength: float) -> tuple[float, str]:
    """
    Engine-specific multiplier from validated research metrics.
    RANGE (phase9_9): 0.8–1.3 | TREND (trend_rf_v40): 1.0–1.5
    """
    engine = str(engine or "")
    regime = str(regime).upper()
    strength = max(0.0, min(float(regime_strength), 1.0))

    if engine == RANGE_MODEL_ID and regime == "RANGE":
        # PF ~1.06 — modest uplift when range conviction is present.
        pf_norm = min(PHASE99_VALIDATED_PF / 1.2, 1.0)
        span = RANGE_ENGINE_FACTOR_MAX - RANGE_ENGINE_FACTOR_MIN
        factor = RANGE_ENGINE_FACTOR_MIN + span * (0.45 * strength + 0.55 * pf_norm)
        factor = max(RANGE_ENGINE_FACTOR_MIN, min(RANGE_ENGINE_FACTOR_MAX, factor))
        return round(factor, 4), f"range engine PF~{PHASE99_VALIDATED_PF} factor {factor:.2f}"

    if engine == TREND_MODEL_ID and regime == "TREND":
        # Phase 13.10: PF 1.21, WF 0.83, MC 100%.
        validation_score = (
            0.40 * min(TREND_RF_VALIDATED_PF / 1.5, 1.0)
            + 0.35 * TREND_RF_WF_ROBUSTNESS
            + 0.25 * TREND_RF_MONTE_CARLO
        )
        span = TREND_ENGINE_FACTOR_MAX - TREND_ENGINE_FACTOR_MIN
        factor = TREND_ENGINE_FACTOR_MIN + span * (0.5 * strength + 0.5 * validation_score)
        factor = max(TREND_ENGINE_FACTOR_MIN, min(TREND_ENGINE_FACTOR_MAX, factor))
        return round(factor, 4), "trend engine validated"

    return 1.0, "neutral engine factor"
