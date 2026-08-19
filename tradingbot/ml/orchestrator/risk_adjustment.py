"""Risk adjustment layer — drawdown, streak, volatility, spread, drift."""

from __future__ import annotations

from dataclasses import dataclass, field

from tradingbot.ml.orchestrator.schema import OrchestratorConfig, OrchestratorSnapshot, RiskState


@dataclass
class RiskAdjustmentResult:
    score_multiplier: float = 1.0
    force_wait: bool = False
    reduce_frequency: bool = False
    risk_state: str = RiskState.NORMAL.value
    reasons: list[str] = field(default_factory=list)


@dataclass
class RiskAdjustmentLayer:
    config: OrchestratorConfig | None = None

    def __post_init__(self) -> None:
        self.config = self.config or OrchestratorConfig()

    def evaluate(self, snapshot: OrchestratorSnapshot, ensemble_score: float) -> RiskAdjustmentResult:
        cfg = self.config
        assert cfg is not None
        result = RiskAdjustmentResult()
        feats = snapshot.features_snapshot or {}

        spread_regime = float(feats.get("spread_regime", feats.get("spread_spike", 0.0)))
        if spread_regime >= cfg.spread_block:
            result.force_wait = True
            result.risk_state = RiskState.BLOCKED.value
            result.reasons.append("High spread regime — trading blocked")
            return result

        if snapshot.feature_drift_score >= cfg.drift_block:
            result.force_wait = True
            result.risk_state = RiskState.BLOCKED.value
            result.reasons.append("Severe feature drift — trading blocked")
            return result

        if snapshot.max_drawdown_r >= cfg.drawdown_block_r:
            result.force_wait = True
            result.risk_state = RiskState.BLOCKED.value
            result.reasons.append(f"Drawdown {snapshot.max_drawdown_r:.1f}R exceeds block threshold")
            return result

        multiplier = 1.0

        if snapshot.max_drawdown_r >= cfg.drawdown_caution_r:
            multiplier *= 0.7
            result.risk_state = RiskState.CAUTION.value
            result.reasons.append("Drawdown elevated — confidence reduced 30%")

        if snapshot.loss_streak >= cfg.loss_streak_restrict:
            multiplier *= 0.6
            result.reduce_frequency = True
            result.risk_state = RiskState.RESTRICTED.value
            result.reasons.append(f"Loss streak {snapshot.loss_streak} — trade frequency reduced")
        elif snapshot.loss_streak >= cfg.loss_streak_caution:
            multiplier *= 0.85
            result.reduce_frequency = True
            if result.risk_state == RiskState.NORMAL.value:
                result.risk_state = RiskState.CAUTION.value
            result.reasons.append(f"Loss streak {snapshot.loss_streak} — caution applied")

        vol = float(feats.get("volatility_regime", 0.5))
        if vol >= 0.75:
            multiplier *= 0.8
            result.reduce_frequency = True
            result.reasons.append("High volatility — reduced exposure")

        if snapshot.feature_drift_score >= cfg.drift_warning:
            multiplier *= 0.85
            result.reasons.append("Feature drift warning — confidence reduced")

        if snapshot.calibration_error >= 0.15:
            multiplier *= 0.9
            result.reasons.append("Calibration error elevated")

        adjusted = ensemble_score * multiplier
        if result.reduce_frequency and abs(adjusted) < cfg.min_score + 0.1:
            result.force_wait = True
            result.reasons.append("Score below elevated threshold during restricted mode")

        result.score_multiplier = round(multiplier, 4)
        return result
