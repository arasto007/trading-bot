"""Ensemble scoring — weighted merge of all shadow signals."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.abtest.schema import WINNER_HYBRID, WINNER_RULE
from tradingbot.ml.orchestrator.schema import OrchestratorConfig, OrchestratorSnapshot, SourceContributions
from tradingbot.ml.orchestrator.signals import extract_signals


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_score(score: float) -> float:
    return round(_clamp(score, -1.0, 1.0), 6)


@dataclass
class EnsembleEngine:
    config: OrchestratorConfig | None = None

    def __post_init__(self) -> None:
        self.config = self.config or OrchestratorConfig()

    def compute_weights(self, snapshot: OrchestratorSnapshot) -> tuple[float, float, float]:
        cfg = self.config
        assert cfg is not None
        regime = snapshot.regime.lower()
        ml_w = 0.50
        rule_w = 0.30
        hybrid_w = cfg.hybrid_weight_base

        if regime == "trend":
            ml_w, rule_w, hybrid_w = 0.55, 0.25, 0.20
        elif regime == "range":
            ml_w, rule_w, hybrid_w = 0.35, 0.45, 0.20
        elif regime == "high_volatility":
            ml_w, rule_w, hybrid_w = 0.40, 0.35, 0.25

        if snapshot.performance_state in ("DEGRADED", "FAILED"):
            ml_w *= 0.85
            rule_w = min(cfg.rule_weight_max, rule_w * 1.10)

        ml_w = _clamp(ml_w, cfg.ml_weight_min, cfg.ml_weight_max)
        rule_w = _clamp(rule_w, cfg.rule_weight_min, cfg.rule_weight_max)
        hybrid_w = max(0.10, hybrid_w)
        total = ml_w + rule_w + hybrid_w
        if total <= 0:
            return 0.4, 0.3, 0.3
        return round(ml_w / total, 6), round(rule_w / total, 6), round(hybrid_w / total, 6)

    def ab_winner_bias(self, snapshot: OrchestratorSnapshot) -> float:
        cfg = self.config
        assert cfg is not None
        if snapshot.ab_winner == WINNER_HYBRID:
            return cfg.ab_bias
        if snapshot.ab_winner == WINNER_RULE:
            return -cfg.ab_bias
        return 0.0

    def performance_adjustment(self, snapshot: OrchestratorSnapshot) -> float:
        adj = 0.0
        if snapshot.paper_expectancy_r > 0:
            adj += min(0.1, snapshot.paper_expectancy_r * 0.02)
        if snapshot.max_drawdown_r > self.config.drawdown_caution_r:
            adj -= 0.08
        if snapshot.loss_streak >= self.config.loss_streak_caution:
            adj -= 0.05 * min(snapshot.loss_streak - self.config.loss_streak_caution + 1, 3)
        return round(adj, 6)

    def compute(self, snapshot: OrchestratorSnapshot) -> SourceContributions:
        cfg = self.config
        assert cfg is not None
        signals = extract_signals(snapshot)
        ml_w, rule_w, hybrid_w = self.compute_weights(snapshot)
        ab_bias = self.ab_winner_bias(snapshot)
        perf_adj = self.performance_adjustment(snapshot)

        raw = (
            signals["ml"] * ml_w
            + signals["rule"] * rule_w
            + signals["hybrid"] * hybrid_w
            + ab_bias
            + perf_adj
        )
        return SourceContributions(
            ml_signal=signals["ml"],
            rule_signal=signals["rule"],
            hybrid_score=signals["hybrid"],
            ab_bias=ab_bias,
            performance_adjustment=perf_adj,
            ml_weight=round(ml_w, 6),
            rule_weight=round(rule_w, 6),
            hybrid_weight=round(hybrid_w, 6),
            raw_score=round(raw, 6),
            adjusted_score=_normalize_score(raw),
        )
