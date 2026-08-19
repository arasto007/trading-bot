"""Model improvement suggestions — no automatic retraining."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.improvement.recommendation import ReportBundle
from tradingbot.ml.improvement.schema import ModelSuggestion


@dataclass
class ModelOptimizer:
    """Suggest algorithm, parameter, and training window changes."""

    base_dir: str | None = None

    def analyze(self, symbol: str, timeframe: str = "M5") -> list[ModelSuggestion]:
        bundle = ReportBundle.load(self.base_dir)
        rankings = bundle.model_comparison.get("rankings", [])
        experiments = bundle.experiment_report.get("experiments", [])
        suggestions: list[ModelSuggestion] = []

        if not rankings:
            suggestions.append(
                ModelSuggestion(
                    model_name="logistic",
                    suggestion_type="baseline",
                    recommendation="run baseline comparison across logistic, xgboost, lightgbm",
                    parameter_ranges={"models": ["logistic", "xgboost", "lightgbm"]},
                    confidence=0.65,
                )
            )
            return suggestions

        best = rankings[0]
        best_name = str(best.get("model_name", "unknown"))
        for entry in rankings:
            name = str(entry.get("model_name", ""))
            expected_r = float(entry.get("expected_R", 0.0))
            calibration = float(entry.get("calibration_error", 0.1))
            stability = float(entry.get("stability_score", 0.5))

            if calibration > 0.12:
                suggestions.append(
                    ModelSuggestion(
                        model_name=name,
                        suggestion_type="calibration",
                        recommendation="run Platt scaling or isotonic calibration on validation split",
                        parameter_ranges={"calibration_methods": ["platt", "isotonic"]},
                        confidence=0.74,
                    )
                )

            if stability < 0.5:
                suggestions.append(
                    ModelSuggestion(
                        model_name=name,
                        suggestion_type="training_window",
                        recommendation="extend walk-forward windows and reduce feature count",
                        parameter_ranges={"train_window_bars": [2000, 5000, 10000]},
                        confidence=0.71,
                    )
                )

            if expected_r < 0.1 and name == best_name:
                suggestions.append(
                    ModelSuggestion(
                        model_name=name,
                        suggestion_type="algorithm_change",
                        recommendation="evaluate alternative model family with same features",
                        parameter_ranges={"candidates": ["xgboost", "lightgbm", "logistic"]},
                        confidence=0.69,
                    )
                )

        if experiments:
            latest = experiments[-1]
            params = latest.get("parameters", {})
            suggestions.append(
                ModelSuggestion(
                    model_name=str(latest.get("model_name", best_name)),
                    suggestion_type="parameter_ranges",
                    recommendation="sweep threshold and regularization in offline experiments",
                    parameter_ranges={
                        "threshold": [0.45, 0.50, 0.55, 0.60],
                        "regularization": ["low", "medium", "high"],
                        "current_threshold": params.get("threshold", 0.5),
                    },
                    confidence=0.77,
                )
            )

        return suggestions
