"""Passive request/fill telemetry schema — research only.

Does not send orders, import live.py, or attach to the execution adapter.
Live order logic is unchanged. This module records observations that already
exist; it cannot create fills.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = (
    "request_ts",
    "requested_price",
    "requested_volume",
    "symbol",
    "side",
    "order_ticket",
    "deal_ticket",
    "fill_ts",
    "fill_price",
    "fill_volume",
    "retcode",
    "rejection_reason",
    "partial_fill",
    "slippage",
)

JOURNAL_PRESENT = (
    "symbol",
    "requested_price",
    "fill_price",
    "lot",
    "ticket",
    "success",
    "message",
    "sl",
    "tp",
    "ts",
    "mode",
    "direction",
)

JOURNAL_MISSING = (
    "request_ts",
    "fill_ts",
    "requested_volume",
    "order_ticket",
    "deal_ticket",
    "fill_volume",
    "retcode",
    "rejection_reason",
    "partial_fill",
    "slippage_as_price",
)


@dataclass(frozen=True)
class RequestFillRecord:
    request_ts: str | None = None
    requested_price: float | None = None
    requested_volume: float | None = None
    symbol: str = ""
    side: str = ""
    order_ticket: int | None = None
    deal_ticket: int | None = None
    fill_ts: str | None = None
    fill_price: float | None = None
    fill_volume: float | None = None
    retcode: int | None = None
    rejection_reason: str | None = None
    partial_fill: bool | None = None
    slippage: float | None = None
    source: str = "passive_observation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_complete_pair(self) -> bool:
        return all(
            [
                self.request_ts,
                self.requested_price is not None,
                self.requested_volume is not None,
                self.symbol,
                self.order_ticket is not None,
                self.deal_ticket is not None,
                self.fill_ts,
                self.fill_price is not None,
                self.fill_volume is not None,
                self.retcode is not None,
            ]
        )


class PassiveRequestFillRecorder:
    """JSONL observer. Has no send/execute/place_order methods."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_observation(self, record: RequestFillRecord) -> None:
        if record.source != "passive_observation":
            raise ValueError("only passive_observation records are accepted")
        line = json.dumps(record.to_dict(), default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def audit_journal_schema(journal_source: str) -> dict[str, Any]:
    present = [name for name in JOURNAL_PRESENT if name in journal_source]
    return {
        "schema_has_requested_and_fill_columns": "requested_price" in journal_source
        and "fill_price" in journal_source,
        "present": present,
        "missing_for_request_fill_pair": list(JOURNAL_MISSING),
        "pairs_cannot_be_synthesized": True,
        "wired_into_live_execution": False,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
