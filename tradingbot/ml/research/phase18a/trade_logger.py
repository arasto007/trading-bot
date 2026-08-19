"""Phase 18A — shadow trade logger (no execution)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ShadowTradeLogger:
    """Append-only decision/trade log — never reaches execution."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def log(self, record: dict[str, Any]) -> None:
        payload = dict(record)
        payload["order_send"] = False
        payload["execution"] = False
        self.records.append(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "18A",
            "count": len(self.records),
            "order_send_calls": 0,
            "records": self.records,
        }
