"""Improvement analyzer — identify opportunities from research outputs."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.improvement.recommendation import ReportBundle
from tradingbot.ml.improvement.schema import ImprovementOpportunity


@dataclass
class ImprovementAnalyzer:
    """Analyze research, shadow, and paper trading reports for improvement opportunities."""

    base_dir: str | None = None

    def analyze(self, symbol: str, timeframe: str = "M5") -> list[ImprovementOpportunity]:
        bundle = ReportBundle.load(self.base_dir)
        opportunities: list[ImprovementOpportunity] = []

        paper = bundle.paper_trading.get("metrics", {})
        max_dd = float(paper.get("max_drawdown_r", 0.0))
        win_rate = float(paper.get("win_rate", 0.0))
        expectancy = float(paper.get("expectancy_r", paper.get("total_return_r", 0.0)))

        monitoring = bundle.monitoring_summary
        drift = float(monitoring.get("feature_drift_score", 0.0))
        degradation = monitoring.get("degradation", {})
        deg_status = str(degradation.get("status", "HEALTHY"))

        if max_dd > 15.0:
            opportunities.append(
                ImprovementOpportunity(
                    issue="high drawdown during high volatility",
                    recommendation="apply volatility filter",
                    confidence=0.82 if max_dd > 20 else 0.70,
                    category="risk",
                    expected_impact="reduce max drawdown",
                    source="paper_trading",
                )
            )

        if win_rate < 0.50 and paper:
            opportunities.append(
                ImprovementOpportunity(
                    issue="win rate below 50%",
                    recommendation="raise probability threshold and review feature subset",
                    confidence=0.75,
                    category="threshold",
                    expected_impact="improve trade quality",
                    source="paper_trading",
                )
            )

        if drift >= 0.20:
            opportunities.append(
                ImprovementOpportunity(
                    issue="elevated feature drift",
                    recommendation="retrain with recent window and remove unstable features",
                    confidence=0.78,
                    category="features",
                    expected_impact="improve model stability",
                    source="monitoring",
                )
            )

        if deg_status in ("DEGRADED", "FAILED"):
            opportunities.append(
                ImprovementOpportunity(
                    issue=f"performance {deg_status.lower()}",
                    recommendation="run walk-forward revalidation and compare models",
                    confidence=0.80,
                    category="model",
                    expected_impact="restore expected R",
                    source="monitoring",
                )
            )

        unstable = bundle.feature_research.get("unstable_features", [])
        if unstable:
            opportunities.append(
                ImprovementOpportunity(
                    issue=f"unstable features detected ({len(unstable)})",
                    recommendation="remove or modify unstable features in next experiment",
                    confidence=0.72,
                    category="features",
                    expected_impact="reduce noise",
                    source="feature_research",
                )
            )

        best_model = bundle.model_comparison.get("best_model")
        rankings = bundle.model_comparison.get("rankings", [])
        if rankings and float(rankings[0].get("calibration_error", 0)) > 0.12:
            opportunities.append(
                ImprovementOpportunity(
                    issue="calibration error elevated on best model",
                    recommendation="apply calibration sweep and threshold optimization",
                    confidence=0.76,
                    category="calibration",
                    expected_impact="better probability alignment",
                    source="model_comparison",
                )
            )

        if expectancy < 0 and paper:
            opportunities.append(
                ImprovementOpportunity(
                    issue="negative expected R in paper trading",
                    recommendation="reduce trade frequency and tighten hybrid score gate",
                    confidence=0.85,
                    category="strategy",
                    expected_impact="reduce losses",
                    source="paper_trading",
                )
            )

        if not opportunities:
            opportunities.append(
                ImprovementOpportunity(
                    issue="no critical issues detected",
                    recommendation="continue shadow validation and scheduled research experiments",
                    confidence=0.60,
                    category="general",
                    expected_impact="maintain performance",
                    source="analyzer",
                )
            )

        return sorted(opportunities, key=lambda o: o.confidence, reverse=True)
