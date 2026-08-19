"""Phase 33D — forensic rejection event schema."""

from __future__ import annotations

import hashlib
import inspect
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ForensicRejectionEvent:
    event_id: str
    symbol: str
    timeframe: str
    timestamp: str
    bar_index: int
    closed_bar_time: str
    current_bar_time: str
    feature_checksum: str
    dataset_checksum: str
    probability: float | None
    confidence: float | None
    quality_score: float | None
    risk_score: float | None
    decision: str
    regime: str
    trend: str | None
    adx: float | None
    atr: float | None
    rsi: float | None
    spread: float | None
    htf_trend: int | None
    reason: str
    module: str
    function: str
    line_number: int
    call_stack_hash: str
    cycle_id: int
    trade_id: str | None = None
    direction: str = ""
    filter_chain: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_event(
    *,
    module: str,
    function: str,
    reason: str,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    timestamp: str = "",
    bar_index: int = 0,
    closed_bar_time: str = "",
    current_bar_time: str = "",
    feature_checksum: str = "",
    dataset_checksum: str = "",
    probability: float | None = None,
    confidence: float | None = None,
    quality_score: float | None = None,
    risk_score: float | None = None,
    decision: str = "HOLD",
    regime: str = "",
    trend: str | None = None,
    adx: float | None = None,
    atr: float | None = None,
    rsi: float | None = None,
    spread: float | None = None,
    htf_trend: int | None = None,
    cycle_id: int = 0,
    trade_id: str | None = None,
    direction: str = "",
    filter_chain: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> ForensicRejectionEvent:
    try:
        line_no = inspect.getsourcelines(inspect.currentframe().f_back)[1]  # type: ignore[union-attr]
    except Exception:
        line_no = 0
    stack_key = f"{module}:{function}:{reason}"
    return ForensicRejectionEvent(
        event_id=uuid.uuid4().hex[:16],
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp or closed_bar_time,
        bar_index=bar_index,
        closed_bar_time=closed_bar_time,
        current_bar_time=current_bar_time,
        feature_checksum=feature_checksum,
        dataset_checksum=dataset_checksum,
        probability=probability,
        confidence=confidence,
        quality_score=quality_score,
        risk_score=risk_score,
        decision=decision,
        regime=regime,
        trend=trend,
        adx=adx,
        atr=atr,
        rsi=rsi,
        spread=spread,
        htf_trend=htf_trend,
        reason=reason,
        module=module,
        function=function,
        line_number=line_no,
        call_stack_hash=hashlib.sha256(stack_key.encode()).hexdigest()[:12],
        cycle_id=cycle_id,
        trade_id=trade_id,
        direction=direction,
        filter_chain=list(filter_chain or []),
        extra=dict(extra or {}),
    )
