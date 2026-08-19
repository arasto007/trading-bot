"""Hypothesis management for ML research."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.research.schema import Hypothesis, HypothesisStatus, new_hypothesis_id, utc_now_iso


def hypotheses_path(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "research" / "hypotheses.json"


@dataclass
class HypothesisManager:
    """Store and update research hypotheses."""

    base_dir: str | Path | None = None

    @property
    def path(self) -> Path:
        return hypotheses_path(self.base_dir)

    def _load(self) -> list[Hypothesis]:
        if not self.path.is_file():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        items = data.get("hypotheses", data if isinstance(data, list) else [])
        return [Hypothesis.from_dict(h) for h in items]

    def _save(self, hypotheses: list[Hypothesis]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": utc_now_iso(), "hypotheses": [h.to_dict() for h in hypotheses]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.path

    def add(self, description: str, target_metric: str = "expected_R") -> Hypothesis:
        hypotheses = self._load()
        hyp = Hypothesis(
            id=new_hypothesis_id(),
            description=description,
            target_metric=target_metric,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        hypotheses.append(hyp)
        self._save(hypotheses)
        return hyp

    def link_experiment(self, hypothesis_id: str, experiment_id: str) -> Hypothesis | None:
        hypotheses = self._load()
        for hyp in hypotheses:
            if hyp.id == hypothesis_id:
                if experiment_id not in hyp.experiment_ids:
                    hyp.experiment_ids.append(experiment_id)
                hyp.status = HypothesisStatus.TESTING.value
                hyp.updated_at = utc_now_iso()
                self._save(hypotheses)
                return hyp
        return None

    def update_result(
        self,
        hypothesis_id: str,
        *,
        result: str,
        confidence: float,
        status: str | None = None,
    ) -> Hypothesis | None:
        hypotheses = self._load()
        for hyp in hypotheses:
            if hyp.id == hypothesis_id:
                hyp.result = result
                hyp.confidence = confidence
                hyp.status = status or hyp.status
                hyp.updated_at = utc_now_iso()
                self._save(hypotheses)
                return hyp
        return None

    def list_all(self) -> list[Hypothesis]:
        return self._load()

    def ensure_defaults(self) -> list[Hypothesis]:
        if self._load():
            return self._load()
        defaults = [
            ("SMC features improve London session performance", "expected_R"),
            ("High volatility filtering reduces drawdown", "max_drawdown"),
        ]
        for desc, metric in defaults:
            self.add(desc, metric)
        return self._load()
