"""Immutable audit trail — append-only JSONL."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root


def audit_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "audit"


def audit_log_path(symbol: str, base_dir: str | Path | None = None) -> Path:
    return audit_dir(base_dir) / f"audit_{symbol.upper()}.jsonl"


@dataclass
class AuditRecord:
    decision_timestamp: str
    model_version: str
    feature_version: str
    dataset_fingerprint: str
    policy_configuration: dict[str, Any] = field(default_factory=dict)
    readiness_score: float = 0.0
    gate_state: str = "UNKNOWN"
    reasoning_chain: list[str] = field(default_factory=list)
    symbol: str = ""
    timeframe: str = ""
    event_type: str = "shadow_decision"
    recorded_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLogger:
    """
    Append-only immutable audit log.

    Never overwrites existing entries.
    """

    def __init__(self, symbol: str, base_dir: str | Path | None = None) -> None:
        self.symbol = symbol.upper()
        self.base_dir = base_dir
        audit_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return audit_log_path(self.symbol, self.base_dir)

    def append(self, record: AuditRecord | dict[str, Any]) -> Path:
        payload = record.to_dict() if isinstance(record, AuditRecord) else dict(record)
        if not payload.get("recorded_at"):
            payload["recorded_at"] = datetime.now(timezone.utc).isoformat()
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
