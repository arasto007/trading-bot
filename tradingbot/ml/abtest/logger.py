"""A/B test JSONL logger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.abtest.schema import ABDecisionRecord


def abtest_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "abtest"


def ab_records_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return abtest_dir(base_dir) / f"ab_records_{symbol.upper()}.jsonl"


class ABTestLogger:
    """Persist A/B decision records to data/ml/abtest/."""

    def __init__(self, symbol: str, base_dir: str | Path | None = None) -> None:
        self.symbol = symbol.upper()
        self.base_dir = base_dir
        abtest_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return ab_records_path(self.symbol, self.base_dir)

    def log(self, record: ABDecisionRecord | dict[str, Any]) -> Path:
        payload = record.to_dict() if isinstance(record, ABDecisionRecord) else dict(record)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self.path

    def log_many(self, records: list[ABDecisionRecord]) -> Path:
        for record in records:
            self.log(record)
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
