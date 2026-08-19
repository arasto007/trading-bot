"""Experiment tracking — append-only JSONL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.research.schema import ExperimentRecord, new_experiment_id, utc_now_iso


def research_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "research"


def experiments_path(base_dir: str | Path | None = None) -> Path:
    return research_dir(base_dir) / "experiments.jsonl"


class ExperimentTracker:
    """Append-only experiment log — never overwrites prior records."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir
        research_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return experiments_path(self.base_dir)

    def append(self, record: ExperimentRecord | dict[str, Any]) -> Path:
        payload = record.to_dict() if isinstance(record, ExperimentRecord) else dict(record)
        if not payload.get("experiment_id"):
            payload["experiment_id"] = new_experiment_id()
        if not payload.get("timestamp"):
            payload["timestamp"] = utc_now_iso()
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
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

    def count(self) -> int:
        return len(self.read_all())

    def find_by_id(self, experiment_id: str) -> dict[str, Any] | None:
        for row in self.read_all():
            if row.get("experiment_id") == experiment_id:
                return row
        return None
