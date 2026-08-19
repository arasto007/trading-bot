"""Phase 14.2A — central confidence calibrator."""

from __future__ import annotations

from tradingbot.ml.confidence_engine.calibration_policy import (
    DEFAULT_CALIBRATION_POLICY,
    CalibrationPolicy,
    MAX_CONFIDENCE,
)
from tradingbot.ml.confidence_engine.calibration_trace import confidence_band
from tradingbot.ml.confidence_engine.calibration_types import CalibratedConfidence, RawConfidence
from tradingbot.ml.confidence_engine.engine_calibrator import engine_calibration_factor
from tradingbot.ml.confidence_engine.regime_calibrator import RegimeCalibrator
from tradingbot.ml.confidence_engine.session_adjuster import SessionAdjuster
from tradingbot.ml.confidence_engine.volatility_adjuster import VolatilityAdjuster, classify_volatility


def clamp(value: float, low: float = 0.0, high: float = MAX_CONFIDENCE) -> float:
    return max(low, min(high, float(value)))


class ConfidenceCalibrator:
    """Transform raw Phase 14.1 confidence into calibrated confidence."""

    def __init__(
        self,
        *,
        policy: CalibrationPolicy | None = None,
        regime_calibrator: RegimeCalibrator | None = None,
        session_adjuster: SessionAdjuster | None = None,
        volatility_adjuster: VolatilityAdjuster | None = None,
    ) -> None:
        self.policy = policy or DEFAULT_CALIBRATION_POLICY
        self.regime_calibrator = regime_calibrator or RegimeCalibrator()
        self.session_adjuster = session_adjuster or SessionAdjuster()
        self.volatility_adjuster = volatility_adjuster or VolatilityAdjuster()

    def calibrate(self, raw_confidence_context: RawConfidence) -> CalibratedConfidence:
        raw = raw_confidence_context
        adjustments: list[str] = []
        explanation: list[str] = []

        if raw.regime == "NO_TRADE" or raw.engine is None:
            return CalibratedConfidence(
                calibrated_value=0.0,
                adjustment_factor=0.0,
                confidence_band="ZERO",
                explanation=["NO_TRADE regime — calibration blocked"],
                trace=["Regime NO_TRADE forces zero confidence"],
                adjustments=["NO_TRADE force zero"],
                raw_value=raw.raw_value,
                engine=raw.engine,
                regime=raw.regime,
            )

        vol_state = raw.volatility_state or classify_volatility(raw.volatility)
        vol_factor, vol_label, vol_state = self.volatility_adjuster.factor(raw.volatility)
        adjustments.append(vol_label)

        if vol_state == "EXTREME":
            return CalibratedConfidence(
                calibrated_value=0.0,
                adjustment_factor=0.0,
                confidence_band="ZERO",
                explanation=["EXTREME volatility — reject"],
                trace=[vol_label, "Calibration blocked"],
                adjustments=adjustments,
                raw_value=raw.raw_value,
                engine=raw.engine,
                regime=raw.regime,
            )

        engine_factor, engine_label = engine_calibration_factor(
            engine=raw.engine,
            regime=raw.regime,
            regime_strength=raw.regime_strength,
        )
        adjustments.append(engine_label)

        regime_factor, regime_label = self.regime_calibrator.factor(raw.regime, volatility_state=vol_state)
        adjustments.append(regime_label)

        session_factor, session_label, session_name = self.session_adjuster.factor(raw.session)
        adjustments.append(session_label)

        if raw.raw_value < self.policy.min_raw_confidence:
            calibrated = 0.0
            adj_factor = 0.0
            explanation.append(f"raw confidence {raw.raw_value:.4f} below minimum {self.policy.min_raw_confidence}")
        else:
            product = engine_factor * regime_factor * session_factor * vol_factor
            calibrated = clamp(raw.raw_value * product)
            adj_factor = calibrated / raw.raw_value if raw.raw_value > 0 else 0.0
            explanation.extend(
                [
                    engine_label,
                    f"{session_name} session adjustment",
                    vol_label.replace("+0%", "neutral"),
                ]
            )

        band = confidence_band(calibrated)
        trace = [
            f"Raw confidence {raw.raw_value:.4f}",
            f"Engine {raw.engine} regime {raw.regime}",
            *adjustments,
            f"Calibrated {calibrated:.4f} (factor {adj_factor:.2f})",
            f"Band {band}",
        ]

        return CalibratedConfidence(
            calibrated_value=round(calibrated, 6),
            adjustment_factor=round(adj_factor, 6),
            confidence_band=band,  # type: ignore[arg-type]
            explanation=explanation,
            trace=trace,
            adjustments=adjustments,
            raw_value=raw.raw_value,
            engine=raw.engine,
            regime=raw.regime,
        )
