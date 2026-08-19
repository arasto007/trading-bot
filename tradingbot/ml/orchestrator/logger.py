"""Final shadow decision JSONL logger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.orchestrator.schema import FinalDecision


def orchestrator_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "orchestrator"


def final_decisions_path(base_dir: str | Path | None = None) -> Path:
    return orchestrator_dir(base_dir) / "final_decisions.jsonl"


class OrchestratorLogger:
    """Append final shadow decisions to data/ml/orchestrator/final_decisions.jsonl."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir
        orchestrator_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return final_decisions_path(self.base_dir)

    def log(self, decision: FinalDecision | dict[str, Any]) -> Path:
        payload = decision.to_dict() if isinstance(decision, FinalDecision) else dict(decision)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self.path

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
