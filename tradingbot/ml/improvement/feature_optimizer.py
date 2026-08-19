"""Feature improvement suggestions — recommendations only."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tradingbot.ml.improvement.recommendation import ReportBundle, feature_improvement_path
from tradingbot.ml.improvement.schema import FeatureSuggestion, SuggestionAction


@dataclass
class FeatureOptimizer:
    """Suggest ADD / REMOVE / MODIFY feature changes without touching the pipeline."""

    base_dir: str | None = None
    low_contribution_threshold: float = 0.05
    stability_threshold: float = 0.40

    def analyze(self, symbol: str, timeframe: str = "M5") -> dict:
        bundle = ReportBundle.load(self.base_dir)
        report = bundle.feature_research
        importance = report.get("importance", {})
        stability = report.get("stability_scores", {})
        drift = report.get("drift_scores", {})
        correlations = report.get("correlation_changes", {})
        regime_dep = report.get("regime_dependency", {})

        suggestions: list[FeatureSuggestion] = []

        for name, score in importance.items():
            if score < self.low_contribution_threshold:
                suggestions.append(
                    FeatureSuggestion(
                        feature=name,
                        action=SuggestionAction.REMOVE.value,
                        reason="low contribution to label correlation",
                        confidence=round(0.65 + (self.low_contribution_threshold - score), 4),
                        details={"importance": score},
                    )
                )

        for name, score in stability.items():
            if score < self.stability_threshold:
                suggestions.append(
                    FeatureSuggestion(
                        feature=name,
                        action=SuggestionAction.MODIFY.value,
                        reason="unstable across chronological halves",
                        confidence=round(0.70 + (self.stability_threshold - score) * 0.5, 4),
                        details={"stability": score, "drift": drift.get(name, 0.0)},
                    )
                )

        for name, change in correlations.items():
            if change > 0.30:
                suggestions.append(
                    FeatureSuggestion(
                        feature=name,
                        action=SuggestionAction.MODIFY.value,
                        reason="correlation structure changed over time",
                        confidence=0.68,
                        details={"correlation_change": change},
                    )
                )

        best = report.get("best_features", [])
        for regime, feats in regime_dep.items():
            top = sorted(feats.items(), key=lambda x: x[1], reverse=True)[:3]
            for fname, score in top:
                if fname not in best:
                    suggestions.append(
                        FeatureSuggestion(
                            feature=fname,
                            action=SuggestionAction.ADD.value,
                            reason=f"strong regime-specific signal in {regime}",
                            confidence=round(min(0.9, 0.6 + score), 4),
                            details={"regime": regime, "score": score},
                        )
                    )

        payload = {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "suggestions": [s.to_dict() for s in suggestions],
            "summary": {
                "add": sum(1 for s in suggestions if s.action == SuggestionAction.ADD.value),
                "remove": sum(1 for s in suggestions if s.action == SuggestionAction.REMOVE.value),
                "modify": sum(1 for s in suggestions if s.action == SuggestionAction.MODIFY.value),
            },
        }
        return payload

    def write_report(self, symbol: str, timeframe: str = "M5") -> dict:
        payload = self.analyze(symbol, timeframe)
        path = feature_improvement_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload
