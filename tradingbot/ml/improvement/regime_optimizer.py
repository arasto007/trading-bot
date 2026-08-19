"""Regime-based filter recommendations."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.improvement.recommendation import ReportBundle
from tradingbot.ml.improvement.schema import RegimeSuggestion


@dataclass
class RegimeOptimizer:
    """Suggest session/volatility/trend filters only."""

    base_dir: str | None = None

    def analyze(self, symbol: str, timeframe: str = "M5") -> list[RegimeSuggestion]:
        bundle = ReportBundle.load(self.base_dir)
        session_dep = bundle.feature_research.get("session_dependency", {})
        regime_dep = bundle.feature_research.get("regime_dependency", {})
        paper = bundle.paper_trading.get("session_breakdown", {})
        suggestions: list[RegimeSuggestion] = []

        for session, stats in paper.items():
            if isinstance(stats, dict):
                expected_r = float(stats.get("expected_R", 0.0))
                if expected_r < 0:
                    suggestions.append(
                        RegimeSuggestion(
                            regime=str(session),
                            filter_recommendation=f"apply WAIT filter during {session} session",
                            reason=f"negative expected R ({expected_r:.2f}R) in paper trading",
                            confidence=0.80,
                        )
                    )

        if "high_volatility" in regime_dep or "high_volatility" in str(regime_dep):
            suggestions.append(
                RegimeSuggestion(
                    regime="high_volatility",
                    filter_recommendation="reduce trade frequency when volatility_regime >= 0.75",
                    reason="high volatility regime shows elevated risk",
                    confidence=0.82,
                )
            )

        if "range" in regime_dep:
            suggestions.append(
                RegimeSuggestion(
                    regime="range",
                    filter_recommendation="favor rule-based signals and require higher hybrid score",
                    reason="range regime benefits from rule-heavy filtering",
                    confidence=0.74,
                )
            )

        if "trend" in regime_dep:
            suggestions.append(
                RegimeSuggestion(
                    regime="trend",
                    filter_recommendation="allow ML signals with standard threshold",
                    reason="trend regime supports ML continuation signals",
                    confidence=0.70,
                )
            )

        for session in session_dep:
            suggestions.append(
                RegimeSuggestion(
                    regime=str(session),
                    filter_recommendation=f"session-specific score boost for {session}",
                    reason="regime-dependent feature contribution detected",
                    confidence=0.68,
                )
            )

        if not suggestions:
            suggestions.append(
                RegimeSuggestion(
                    regime="general",
                    filter_recommendation="maintain current regime gates",
                    reason="insufficient regime breakdown data",
                    confidence=0.55,
                )
            )

        return suggestions
