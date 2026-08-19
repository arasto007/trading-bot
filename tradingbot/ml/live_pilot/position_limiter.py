"""Phase 12 — position and trade frequency limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class PositionLimiterState:
    open_positions: int = 0
    trades_today: int = 0
    day_key: str = ""
    consecutive_losses: int = 0
    rejections: list[dict[str, Any]] = field(default_factory=list)


class PositionLimiter:
    def __init__(
        self,
        *,
        max_open_positions: int = 1,
        max_trades_per_day: int = 10,
        max_consecutive_losses: int = 3,
    ) -> None:
        self.max_open_positions = max_open_positions
        self.max_trades_per_day = max_trades_per_day
        self.max_consecutive_losses = max_consecutive_losses
        self._state = PositionLimiterState()

    def _roll_day(self) -> None:
        today = date.today().isoformat()
        if self._state.day_key != today:
            self._state.day_key = today
            self._state.trades_today = 0

    def can_open_position(self) -> tuple[bool, str]:
        self._roll_day()
        if self._state.open_positions >= self.max_open_positions:
            return False, "max_open_positions"
        if self._state.trades_today >= self.max_trades_per_day:
            return False, "max_trades_per_day"
        if self._state.consecutive_losses >= self.max_consecutive_losses:
            return False, "max_consecutive_losses"
        return True, ""

    def record_entry(self) -> None:
        self._roll_day()
        self._state.open_positions += 1
        self._state.trades_today += 1

    def record_exit(self, *, won: bool) -> None:
        self._state.open_positions = max(0, self._state.open_positions - 1)
        if won:
            self._state.consecutive_losses = 0
        else:
            self._state.consecutive_losses += 1

    def sync_open_positions(self, count: int) -> None:
        self._state.open_positions = max(0, count)

    def reject(self, reason: str) -> None:
        self._state.rejections.append({"reason": reason})

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_positions": self._state.open_positions,
            "trades_today": self._state.trades_today,
            "consecutive_losses": self._state.consecutive_losses,
            "max_open_positions": self.max_open_positions,
            "max_trades_per_day": self.max_trades_per_day,
            "max_consecutive_losses": self.max_consecutive_losses,
            "rejections": list(self._state.rejections),
        }
