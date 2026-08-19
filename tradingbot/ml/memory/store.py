"""Decision memory JSONL store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord


def memory_root(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "memory"


def decisions_dir(base_dir: str | Path | None = None) -> Path:
    return memory_root(base_dir) / "decisions"


def outcomes_dir(base_dir: str | Path | None = None) -> Path:
    return memory_root(base_dir) / "outcomes"


def decisions_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return decisions_dir(base_dir) / f"decisions_{symbol.upper()}.jsonl"


def outcomes_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return outcomes_dir(base_dir) / f"outcomes_{symbol.upper()}.jsonl"


class DecisionMemoryStore:
    """Persist shadow decisions and evaluated outcomes as JSONL."""

    def __init__(self, symbol: str, base_dir: str | Path | None = None) -> None:
        self.symbol = symbol.upper()
        self.base_dir = base_dir
        decisions_dir(base_dir).mkdir(parents=True, exist_ok=True)
        outcomes_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def decisions_file(self) -> Path:
        return decisions_path(self.symbol, self.base_dir)

    @property
    def outcomes_file(self) -> Path:
        return outcomes_path(self.symbol, self.base_dir)

    def append_decision(self, record: DecisionRecord | dict[str, Any]) -> Path:
        payload = record.to_dict() if isinstance(record, DecisionRecord) else dict(record)
        with self.decisions_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self.decisions_file

    def append_outcome(self, outcome: OutcomeRecord | dict[str, Any]) -> Path:
        payload = outcome.to_dict() if isinstance(outcome, OutcomeRecord) else dict(outcome)
        with self.outcomes_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self.outcomes_file

    def load_decisions(self) -> list[DecisionRecord]:
        return [DecisionRecord.from_dict(r) for r in self._read_jsonl(self.decisions_file)]

    def load_outcomes(self) -> list[OutcomeRecord]:
        return [OutcomeRecord.from_dict(r) for r in self._read_jsonl(self.outcomes_file)]

    def load_outcomes_by_id(self) -> dict[str, OutcomeRecord]:
        return {o.decision_id: o for o in self.load_outcomes()}

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
