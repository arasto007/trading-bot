"""Research ranking engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.research.experiment_tracker import ExperimentTracker
from tradingbot.ml.research.model_comparison import ModelComparisonEngine
from tradingbot.ml.research.schema import ResearchRankingEntry


@dataclass
class ResearchRanker:
    """Rank models, features, strategies, and experiments."""

    base_dir: str | None = None

    def rank_all(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        model_ranks = self._rank_models(symbol, timeframe)
        experiment_ranks = self._rank_experiments()
        feature_ranks = self._rank_features(symbol, timeframe)

        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "models": [r.to_dict() for r in model_ranks],
            "experiments": [r.to_dict() for r in experiment_ranks],
            "features": [r.to_dict() for r in feature_ranks],
            "strategies": [],
        }
        return payload

    def write_report(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        payload = self.rank_all(symbol, timeframe)
        path = reports_dir(self.base_dir) / "research_ranking.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    def _rank_models(self, symbol: str, timeframe: str) -> list[ResearchRankingEntry]:
        comparison = ModelComparisonEngine(self.base_dir).compare(symbol, timeframe)
        entries: list[ResearchRankingEntry] = []
        for item in comparison.get("rankings", []):
            entries.append(
                ResearchRankingEntry(
                    rank=int(item.get("rank", 0)),
                    name=str(item.get("model_name", "")),
                    category="model",
                    score=float(item.get("overall_score", 0.0)),
                    expected_R=float(item.get("expected_R", 0.0)),
                    stability=float(item.get("stability_score", 0.0)),
                    sample_size=int(item.get("sample_size", 0)),
                    details={"roc_auc": item.get("roc_auc"), "pr_auc": item.get("pr_auc")},
                )
            )
        return entries

    def _rank_experiments(self) -> list[ResearchRankingEntry]:
        rows = ExperimentTracker(self.base_dir).read_all()
        scored = []
        for row in rows:
            metrics = row.get("metrics", {})
            sample = int(metrics.get("predicted_winrate", 0) * 100) if metrics else 0
            score = self._experiment_score(row)
            scored.append((score, row, sample))
        scored.sort(key=lambda x: x[0], reverse=True)

        entries: list[ResearchRankingEntry] = []
        for i, (score, row, sample) in enumerate(scored):
            entries.append(
                ResearchRankingEntry(
                    rank=i + 1,
                    name=row.get("experiment_id", ""),
                    category="experiment",
                    score=round(score, 4),
                    expected_R=float(row.get("expected_R", 0.0)),
                    stability=float(row.get("metrics", {}).get("roc_auc", 0.5)),
                    sample_size=sample,
                    details={"model": row.get("model_name"), "validation": row.get("validation_method")},
                )
            )
        return entries

    def _rank_features(self, symbol: str, timeframe: str) -> list[ResearchRankingEntry]:
        path = reports_dir(self.base_dir) / "feature_research_report.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        importance = data.get("importance", {})
        stability = data.get("stability_scores", {})
        scored = []
        for name, imp in importance.items():
            stab = stability.get(name, 0.5)
            score = imp * 0.6 + stab * 0.4
            scored.append((score, name, imp, stab))
        scored.sort(key=lambda x: x[0], reverse=True)

        entries: list[ResearchRankingEntry] = []
        for i, (score, name, imp, stab) in enumerate(scored[:20]):
            entries.append(
                ResearchRankingEntry(
                    rank=i + 1,
                    name=name,
                    category="feature",
                    score=round(score, 4),
                    expected_R=round(imp, 4),
                    stability=round(stab, 4),
                    sample_size=0,
                )
            )
        return entries

    @staticmethod
    def _experiment_score(row: dict[str, Any]) -> float:
        expected_r = float(row.get("expected_R", 0.0))
        metrics = row.get("metrics", {})
        roc = float(metrics.get("roc_auc", 0.0))
        robustness = float(metrics.get("f1", 0.0))
        return expected_r * 0.4 + roc * 0.35 + robustness * 0.25
