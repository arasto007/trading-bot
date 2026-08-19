"""Model comparison engine — offline ranking only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.artifacts import evaluation_report_path, model_metadata_path, read_metadata
from tradingbot.ml.models.registry import load_registry
from tradingbot.ml.research.schema import ModelComparisonEntry


DEFAULT_MODELS: tuple[str, ...] = ("logistic", "xgboost", "lightgbm")


@dataclass
class ModelComparisonEngine:
    """
    Compare baseline models using stored evaluation reports.

    No automatic model replacement.
    """

    base_dir: str | Path | None = None
    models: tuple[str, ...] = DEFAULT_MODELS

    def compare(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        entries: list[ModelComparisonEntry] = []

        for name in self.models:
            entry = self._load_model_metrics(symbol, timeframe, name)
            if entry:
                entries.append(entry)

        entries.sort(key=lambda e: e.overall_score, reverse=True)
        ranked = [{**e.to_dict(), "rank": i + 1} for i, e in enumerate(entries)]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "models_compared": len(entries),
            "rankings": ranked,
            "best_model": ranked[0]["model_name"] if ranked else None,
            "auto_replacement": False,
        }

    def write_report(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        payload = self.compare(symbol, timeframe)
        path = reports_dir(self.base_dir) / "model_comparison.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    def _load_model_metrics(self, symbol: str, timeframe: str, model_name: str) -> ModelComparisonEntry | None:
        path = evaluation_report_path(symbol, timeframe, model_name, self.base_dir)
        data: dict[str, Any] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            registry = load_registry(self.base_dir)
            for entry in registry:
                if entry.get("name", "").lower() == model_name.lower():
                    data = {"metrics": entry.get("metrics", {}), "trading": entry.get("trading", {})}
                    break

        if not data:
            meta = read_metadata(model_metadata_path(model_name, self.base_dir))
            if meta:
                data = {"metrics": meta.get("metrics", {}), "trading": meta.get("trading", {})}

        metrics = data.get("metrics", {})
        trading = data.get("trading", {})
        simulated = data.get("simulated", {})

        if not metrics and not trading:
            return None

        roc = float(metrics.get("roc_auc", 0.0))
        pr = float(metrics.get("pr_auc", 0.0))
        expected_r = float(trading.get("expected_R", metrics.get("expected_R", 0.0)))
        pf = float(simulated.get("profit_factor", max(expected_r, 0.1) + 0.5))
        dd = float(simulated.get("max_drawdown", abs(min(expected_r, 0)) * 10))
        stability = float(metrics.get("stability_score", 0.5))
        calibration = float(metrics.get("calibration_error", 0.1))
        sample = int(simulated.get("trades_taken", metrics.get("sample_size", 0)))

        overall = self._overall_score(roc, pr, expected_r, stability, calibration, sample)
        return ModelComparisonEntry(
            model_name=model_name,
            roc_auc=round(roc, 4),
            pr_auc=round(pr, 4),
            expected_R=round(expected_r, 4),
            profit_factor=round(pf, 4),
            max_drawdown=round(dd, 4),
            stability_score=round(stability, 4),
            calibration_error=round(calibration, 4),
            overall_score=round(overall, 4),
            sample_size=sample,
        )

    @staticmethod
    def _overall_score(
        roc: float,
        pr: float,
        expected_r: float,
        stability: float,
        calibration: float,
        sample: int,
    ) -> float:
        sample_factor = min(1.0, sample / 200.0) if sample else 0.3
        score = (
            roc * 0.25
            + pr * 0.15
            + max(0.0, min(1.0, (expected_r + 1) / 2)) * 0.30
            + stability * 0.15
            + max(0.0, 1.0 - calibration) * 0.10
            + sample_factor * 0.05
        )
        return max(0.0, min(1.0, score))
