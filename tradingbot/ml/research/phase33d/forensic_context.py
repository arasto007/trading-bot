"""Phase 33D — thread-local forensic context (research only, no production logic)."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

_forensic_ctx: ContextVar["ForensicContext | None"] = ContextVar("phase33d_forensic_ctx", default=None)


@dataclass
class ForensicContext:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    bar_index: int = 0
    closed_bar_time: str = ""
    current_bar_time: str = ""
    cycle_id: int = 0
    feature_checksum: str = ""
    dataset_checksum: str = ""
    htf_bias: int = 0
    portfolio_snapshot: dict[str, Any] = field(default_factory=dict)


def get_ctx() -> ForensicContext | None:
    return _forensic_ctx.get()


def set_ctx(ctx: ForensicContext) -> None:
    _forensic_ctx.set(ctx)


def clear_ctx() -> None:
    _forensic_ctx.set(None)


def row_checksum(row: dict[str, Any]) -> str:
    keys = sorted(k for k in row if not str(k).startswith("_"))
    payload = "|".join(f"{k}={row.get(k)}" for k in keys[:40])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
