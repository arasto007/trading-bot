"""Threshold recommendation engine — shadow outcomes based."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.improvement.recommendation import ReportBundle
from tradingbot.ml.improvement.schema import ThresholdSuggestion
from tradingbot.ml.memory.store import DecisionMemoryStore


@dataclass
class ThresholdRecommendationEngine:
    """Suggest probability threshold changes from shadow and paper metrics."""

    base_dir: str | None = None
    default_threshold: float = 0.50

    def analyze(self, symbol: str, timeframe: str = "M5") -> ThresholdSuggestion:
        bundle = ReportBundle.load(self.base_dir)
        paper = bundle.paper_trading.get("metrics", {})
        optimization = bundle.shadow_optimization

        current = float(optimization.get("best_threshold", self.default_threshold))
        win_rate = float(paper.get("win_rate", 0.0))
        expectancy = float(paper.get("expectancy_r", 0.0))
        trade_freq = float(paper.get("trade_frequency", 0))

        recommended = current
        reason = "maintain current threshold"
        impact = 0.0
        confidence = 0.60

        if win_rate < 0.48 and trade_freq > 50:
            recommended = min(0.75, current + 0.05)
            reason = "low win rate with high trade frequency — tighten threshold"
            impact = 0.05
            confidence = 0.78
        elif win_rate > 0.58 and trade_freq < 30:
            recommended = max(0.40, current - 0.03)
            reason = "strong win rate but low frequency — loosen threshold slightly"
            impact = 0.03
            confidence = 0.72
        elif expectancy < 0:
            recommended = min(0.70, current + 0.08)
            reason = "negative expected R — increase selectivity"
            impact = 0.08
            confidence = 0.82

        store = DecisionMemoryStore(symbol, self.base_dir)
        decisions = store.load_decisions()
        if decisions:
            probs = [float(d.ml_probability) for d in decisions if d.ml_prediction == 1]
            if probs:
                median_prob = sorted(probs)[len(probs) // 2]
                if recommended < median_prob - 0.1:
                    recommended = round(median_prob - 0.05, 2)
                    reason = "align threshold with shadow probability distribution"
                    confidence = max(confidence, 0.70)

        return ThresholdSuggestion(
            current_threshold=round(current, 4),
            recommended_threshold=round(recommended, 4),
            reason=reason,
            expected_R_impact=round(impact, 4),
            confidence=round(confidence, 4),
        )
