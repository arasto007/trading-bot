"""Hybrid decision JSONL logger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.hybrid.schema import HybridDecision


def hybrid_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "hybrid"


def hybrid_log_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return hybrid_dir(base_dir) / f"hybrid_decisions_{symbol.upper()}.jsonl"


class HybridLogger:
    """Append hybrid decisions to data/ml/hybrid/hybrid_decisions_{SYMBOL}.jsonl."""

    def __init__(self, symbol: str, base_dir: str | Path | None = None) -> None:
        self.symbol = symbol.upper()
        self.base_dir = base_dir
        hybrid_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return hybrid_log_path(self.symbol, self.base_dir)

    def log(self, decision: HybridDecision | dict[str, Any]) -> Path:
        payload = decision.to_dict() if isinstance(decision, HybridDecision) else dict(decision)
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
