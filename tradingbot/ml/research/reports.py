"""Research report orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.research.experiment_tracker import ExperimentTracker
from tradingbot.ml.research.feature_research import FeatureResearchAnalyzer
from tradingbot.ml.research.hypothesis import HypothesisManager
from tradingbot.ml.research.model_comparison import ModelComparisonEngine
from tradingbot.ml.research.ranking import ResearchRanker
from tradingbot.ml.research.schema import utc_now_iso


def experiment_report_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "experiment_report.json"


@dataclass
class ResearchReportGenerator:
    """Generate all Phase 7.3 research reports."""

    base_dir: str | Path | None = None

    def run(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        feature_report = FeatureResearchAnalyzer(self.base_dir).write_report(symbol, timeframe)
        model_comparison = ModelComparisonEngine(self.base_dir).write_report(symbol, timeframe)
        ranking = ResearchRanker(self.base_dir).write_report(symbol, timeframe)
        hypotheses = HypothesisManager(self.base_dir).ensure_defaults()

        experiments = ExperimentTracker(self.base_dir).read_all()
        experiment_report = {
            "timestamp": utc_now_iso(),
            "symbol": symbol,
            "timeframe": timeframe,
            "experiment_count": len(experiments),
            "experiments": experiments[-20:],
            "hypotheses": [h.to_dict() for h in hypotheses],
        }
        exp_path = experiment_report_path(self.base_dir)
        exp_path.parent.mkdir(parents=True, exist_ok=True)
        exp_path.write_text(json.dumps(experiment_report, indent=2, ensure_ascii=False), encoding="utf-8")

        return {
            "timestamp": utc_now_iso(),
            "symbol": symbol,
            "timeframe": timeframe,
            "experiment_report": str(exp_path),
            "feature_research_report": str(reports_dir(self.base_dir) / "feature_research_report.json"),
            "model_comparison": str(reports_dir(self.base_dir) / "model_comparison.json"),
            "research_ranking": str(reports_dir(self.base_dir) / "research_ranking.json"),
            "summary": {
                "experiments": len(experiments),
                "hypotheses": len(hypotheses),
                "best_features": feature_report.get("best_features", [])[:5],
                "best_model": model_comparison.get("best_model"),
                "top_experiment": ranking.get("experiments", [{}])[0] if ranking.get("experiments") else None,
            },
        }
