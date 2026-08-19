"""Improvement report generation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tradingbot.ml.improvement.analyzer import ImprovementAnalyzer
from tradingbot.ml.improvement.experiment_queue import ExperimentQueue
from tradingbot.ml.improvement.feature_optimizer import FeatureOptimizer
from tradingbot.ml.improvement.model_optimizer import ModelOptimizer
from tradingbot.ml.improvement.recommendation import improvement_recommendations_path
from tradingbot.ml.improvement.regime_optimizer import RegimeOptimizer
from tradingbot.ml.improvement.schema import utc_now_iso
from tradingbot.ml.improvement.threshold_optimizer import ThresholdRecommendationEngine
from tradingbot.ml.research.reproducibility import dataset_fingerprint, git_commit_hash


@dataclass
class ImprovementReportGenerator:
    """Generate consolidated improvement recommendations."""

    base_dir: str | None = None

    def run(self, symbol: str, timeframe: str = "M5") -> dict:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        opportunities = ImprovementAnalyzer(self.base_dir).analyze(symbol, timeframe)
        feature_report = FeatureOptimizer(self.base_dir).write_report(symbol, timeframe)
        model_suggestions = ModelOptimizer(self.base_dir).analyze(symbol, timeframe)
        threshold = ThresholdRecommendationEngine(self.base_dir).analyze(symbol, timeframe)
        regime = RegimeOptimizer(self.base_dir).analyze(symbol, timeframe)

        queue = ExperimentQueue(self.base_dir)
        queued = queue.populate_from_opportunities(opportunities)

        top = [o.to_dict() for o in opportunities[:5]]
        payload = {
            "timestamp": utc_now_iso(),
            "symbol": symbol,
            "timeframe": timeframe,
            "top_improvements": top,
            "expected_impact": [o.expected_impact for o in opportunities[:5] if o.expected_impact],
            "confidence_scores": [o.confidence for o in opportunities[:5]],
            "experiments_to_run": [q.to_dict() for q in queue.list_all()[:10]],
            "feature_suggestions": feature_report.get("suggestions", [])[:15],
            "model_suggestions": [s.to_dict() for s in model_suggestions],
            "threshold_suggestion": threshold.to_dict(),
            "regime_suggestions": [r.to_dict() for r in regime],
            "reproducibility": {
                "dataset_fingerprint": dataset_fingerprint(symbol, timeframe, self.base_dir),
                "git_commit": git_commit_hash(),
                "validation_method": "chronological_split",
                "random_shuffle": False,
            },
            "auto_apply": False,
            "live_enabled": False,
        }

        path = improvement_recommendations_path(self.base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload
