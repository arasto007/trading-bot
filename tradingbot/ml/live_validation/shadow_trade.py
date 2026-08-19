"""Phase 15D — shadow trade record (no real execution)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ShadowTrade:
    symbol: str
    time: str
    signal: str
    confidence: float
    risk: float
    quality: float
    sl: float | None
    tp: float | None
    entry: float | None
    exit: float | None = None
    pnl: float = 0.0
    duration_bars: int = 0
    reason: list[str] = field(default_factory=list)
    engine: str | None = None
    regime: str | None = None
    risk_gate_allowed: bool = False
    risk_gate_reason: str = ""
    source: str = "ml_shadow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def shadow_trade_from_signal(
    signal: Any,
    *,
    unified: Any | None = None,
    entry: float | None = None,
    risk_allowed: bool = False,
    risk_reason: str = "",
    bar_time: str = "",
) -> ShadowTrade:
    meta = dict(getattr(signal, "metadata", None) or {})
    direction = getattr(getattr(signal, "direction", None), "name", str(meta.get("direction", "HOLD")))
    return ShadowTrade(
        symbol=str(getattr(signal, "symbol", meta.get("symbol", ""))),
        time=bar_time or str(meta.get("unified_timestamp", "")),
        signal=direction,
        confidence=float(getattr(signal, "confidence", meta.get("confidence", 0.0))),
        risk=float(meta.get("risk_percent", unified.risk if unified else 0.0)),
        quality=float(meta.get("quality", unified.quality if unified else 0.0)),
        sl=getattr(signal, "stop_loss", None),
        tp=getattr(signal, "take_profit", None),
        entry=entry,
        reason=list(unified.reason if unified else meta.get("reason", [])),
        engine=meta.get("engine_name", unified.engine if unified else None),
        regime=meta.get("regime", unified.regime if unified else None),
        risk_gate_allowed=risk_allowed,
        risk_gate_reason=risk_reason,
    )
