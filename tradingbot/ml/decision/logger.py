"""Decision JSONL logger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.decision.schema import MLDecision


def decisions_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "decisions"


def shadow_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "shadow"


def decisions_log_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return decisions_dir(base_dir) / f"decisions_{symbol.upper()}.jsonl"


def shadow_log_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return shadow_dir(base_dir) / f"shadow_predictions_{symbol.upper()}.jsonl"


class DecisionLogger:
    """Append ML decisions to data/ml/decisions/decisions_{SYMBOL}.jsonl."""

    def __init__(self, symbol: str, base_dir: str | Path | None = None) -> None:
        self.symbol = symbol.upper()
        self.base_dir = base_dir
        decisions_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return decisions_log_path(self.symbol, self.base_dir)

    def log(self, decision: MLDecision | dict[str, Any]) -> Path:
        payload = decision.to_dict() if isinstance(decision, MLDecision) else dict(decision)
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
