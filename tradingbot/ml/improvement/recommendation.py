"""Load upstream reports for improvement analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root, reports_dir


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@dataclass
class ReportBundle:
    feature_research: dict[str, Any]
    model_comparison: dict[str, Any]
    research_ranking: dict[str, Any]
    experiment_report: dict[str, Any]
    paper_trading: dict[str, Any]
    monitoring_summary: dict[str, Any]
    shadow_optimization: dict[str, Any]

    @classmethod
    def load(cls, base_dir: str | Path | None = None) -> "ReportBundle":
        rep = reports_dir(base_dir)
        return cls(
            feature_research=_load(rep / "feature_research_report.json"),
            model_comparison=_load(rep / "model_comparison.json"),
            research_ranking=_load(rep / "research_ranking.json"),
            experiment_report=_load(rep / "experiment_report.json"),
            paper_trading=_load(rep / "paper_trading_report.json"),
            monitoring_summary=_load(rep / "monitoring_summary.json"),
            shadow_optimization=_load(rep / "shadow_optimization.json"),
        )


def feature_improvement_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "feature_improvement.json"


def improvement_recommendations_path(base_dir: str | Path | None = None) -> Path:
    return reports_dir(base_dir) / "improvement_recommendations.json"


def experiment_queue_path(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "research" / "experiment_queue.json"
