"""Replay portfolio state — delegates accounting to AccountingEngine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pandas as pd

from tradingbot.accounting.engine import AccountingEngine
from tradingbot.ml.research.phase25b.replay_position_state import (
    ReplayPositionState,
    advance_position_bar,
)
from tradingbot.services.exit_mode import ExitMode, resolve_exit_mode


@dataclass
class ReplayOpenPosition:
    position_id: str
    symbol: str
    direction: str
    entry_bar_index: int
    entry_timestamp: str
    entry_price: float
    sl: float | None
    tp: float | None
    lot: float
    regime: str = ""
    engine: str = ""
    confidence: float = 0.0
    risk_percent: float = 0.0
    sizing: dict[str, Any] = field(default_factory=dict)
    exit_bar_index: int | None = None
    exit_timestamp: str | None = None
    exit_reason: str | None = None
    replay_state: ReplayPositionState | None = None


@dataclass
class ReplayPortfolioTracker:
    """Maintains open_positions for RiskGate — accounting via AccountingEngine."""

    candles: pd.DataFrame
    symbol: str
    accounting: AccountingEngine
    exit_mode: ExitMode | str = ExitMode.CURRENT
    _open: list[ReplayOpenPosition] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    lifecycle: list[dict[str, Any]] = field(default_factory=list)
    _candles: pd.DataFrame = field(init=False, repr=False)

    def __post_init__(self) -> None:
        frame = self.candles.copy()
        if not isinstance(frame.index, pd.DatetimeIndex):
            if "time" in frame.columns:
                frame = frame.set_index("time")
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, utc=True))
        self._candles = frame.sort_index()

    @property
    def _closed(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.accounting.ledger.closed_trades]

    def advance_to_bar(self, bar_index: int) -> None:
        if bar_index < 0 or bar_index >= len(self._candles):
            return
        still_open: list[ReplayOpenPosition] = []
        bar = self._candles.iloc[bar_index]
        bar_ts = pd.to_datetime(self._candles.index[bar_index], utc=True).isoformat()
        max_idx = len(self._candles) - 1

        for pos in self._open:
            if bar_index <= pos.entry_bar_index:
                still_open.append(pos)
                continue

            if pos.replay_state is None:
                mode = self.exit_mode if isinstance(self.exit_mode, ExitMode) else resolve_exit_mode(str(self.exit_mode))
                pos.replay_state = ReplayPositionState.from_open(
                    entry_timestamp=pos.entry_timestamp,
                    entry_price=pos.entry_price,
                    entry_bar_index=pos.entry_bar_index,
                    direction=pos.direction,
                    symbol=pos.symbol,
                    sl=pos.sl,
                    tp=pos.tp,
                    lot=pos.lot,
                    exit_mode=mode,
                )
                self.lifecycle.append({
                    "event": "state_init",
                    "position_id": pos.position_id,
                    "bar_index": bar_index,
                    "exit_mode": pos.replay_state.exit_mode,
                })

            closed_now = advance_position_bar(
                pos.replay_state,
                bar,
                bar_index,
                bar_ts,
                max_candle_index=max_idx,
            )

            if closed_now or pos.replay_state.closed:
                exit_info = pos.replay_state.to_exit_info()
                self._finalize_close(pos, exit_info, bar_index)
            else:
                still_open.append(pos)

        self._open = still_open
        self.timeline.append(self.snapshot(bar_index))

    def open_from_execution(
        self,
        *,
        bar_index: int,
        entry_timestamp: str,
        direction: str,
        entry_price: float,
        sl: float | None,
        tp: float | None,
        lot: float,
        regime: str = "",
        engine: str = "",
        confidence: float = 0.0,
        risk_percent: float = 0.0,
        sizing: dict[str, Any] | None = None,
    ) -> ReplayOpenPosition:
        pos = ReplayOpenPosition(
            position_id=uuid4().hex[:12],
            symbol=self.symbol,
            direction=str(direction).upper(),
            entry_bar_index=bar_index,
            entry_timestamp=entry_timestamp,
            entry_price=float(entry_price),
            sl=float(sl) if sl is not None else None,
            tp=float(tp) if tp is not None else None,
            lot=float(lot or 0.01),
            regime=regime,
            engine=engine,
            confidence=confidence,
            risk_percent=risk_percent,
            sizing=dict(sizing or {}),
        )
        self._open.append(pos)
        self.lifecycle.append(
            {
                "event": "open",
                "position_id": pos.position_id,
                "bar_index": bar_index,
                "timestamp": entry_timestamp,
                "symbol": pos.symbol,
                "direction": pos.direction,
                "entry_price": pos.entry_price,
                "sl": pos.sl,
                "tp": pos.tp,
                "lot": pos.lot,
                "regime": pos.regime,
                "engine": pos.engine,
                "risk_percent": pos.risk_percent,
                "sizing": pos.sizing,
            }
        )
        return pos

    def sync_portfolio(self, portfolio: dict[str, Any]) -> None:
        portfolio["open_positions"] = [
            {
                "symbol": p.symbol,
                "direction": p.direction,
                "volume": p.replay_state.remaining_volume if p.replay_state else p.lot,
                "entry_price": p.entry_price,
                "is_buy": p.direction == "BUY",
            }
            for p in self._open
        ]
        portfolio["balance"] = self.accounting.balance
        portfolio["equity"] = self.accounting.equity

    def snapshot(self, bar_index: int) -> dict[str, Any]:
        ts = pd.to_datetime(self._candles.index[bar_index], utc=True).isoformat()
        return {
            "bar_index": bar_index,
            "timestamp": ts,
            "open_count": len(self._open),
            "open_count_symbol": sum(1 for p in self._open if p.symbol == self.symbol),
            "directions": [p.direction for p in self._open],
            "closed_total": len(self.accounting.ledger.closed_trades),
            "realized_pnl": self.accounting.realized_pnl,
            "balance": self.accounting.balance,
            "equity": self.accounting.equity,
        }

    def export_summary(self) -> dict[str, Any]:
        max_open = max((t["open_count"] for t in self.timeline), default=0)
        stuck_at_two = sum(1 for t in self.timeline if t["open_count"] >= 2)
        return {
            "opens": sum(1 for e in self.lifecycle if e.get("event") == "open"),
            "closes": len(self.accounting.ledger.closed_trades),
            "max_concurrent_open": max_open,
            "bars_with_open_gte_2": stuck_at_two,
            "realized_pnl": self.accounting.realized_pnl,
            "final_balance": self.accounting.balance,
            "final_equity": self.accounting.equity,
        }

    def export_closed_trades(self) -> list[dict[str, Any]]:
        return self.accounting.ledger.export_trades()

    def _finalize_close(
        self,
        pos: ReplayOpenPosition,
        exit_info: dict[str, Any],
        exit_bar_index: int,
    ) -> None:
        pos.exit_bar_index = exit_bar_index
        pos.exit_timestamp = str(exit_info.get("exit_timestamp"))
        pos.exit_reason = str(exit_info.get("exit_reason"))
        closed = self.accounting.close_trade(
            exit_info=exit_info,
            entry_timestamp=pos.entry_timestamp,
            entry_price=pos.entry_price,
            direction=pos.direction,
            lot=pos.lot,
            sl=pos.sl,
            tp=pos.tp,
            sizing=pos.sizing,
            regime=pos.regime,
            engine=pos.engine,
            confidence=pos.confidence,
            risk_percent=pos.risk_percent,
            bar_index=pos.entry_bar_index,
            trade_id=pos.position_id,
        )
        lifecycle_row = {
            "event": "close",
            "position_id": pos.position_id,
            "symbol": pos.symbol,
            "direction": pos.direction,
            "entry_bar_index": pos.entry_bar_index,
            "exit_bar_index": exit_bar_index,
            "entry_timestamp": pos.entry_timestamp,
            "exit_timestamp": pos.exit_timestamp,
            "exit_reason": pos.exit_reason,
            "pnl": closed.pnl,
            "duration_bars": exit_info.get("duration_bars"),
            "partial_close_applied": exit_info.get("partial_close_applied"),
            "remaining_lot": exit_info.get("remaining_lot"),
        }
        self.lifecycle.append(lifecycle_row)
