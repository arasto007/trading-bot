"""Phase 12 — emergency kill switch for live pilot."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KillSwitchState:
    active: bool = False
    reason: str = ""
    triggered_at: str | None = None
    triggers: list[dict[str, Any]] = field(default_factory=list)


class PilotKillSwitch:
    """Pilot-layer emergency stop — blocks new entries, preserves logs."""

    def __init__(self) -> None:
        self._state = KillSwitchState()

    @property
    def active(self) -> bool:
        return self._state.active

    @property
    def reason(self) -> str:
        return self._state.reason

    def trigger(self, reason: str, *, detail: dict[str, Any] | None = None) -> None:
        if self._state.active:
            return
        self._state.active = True
        self._state.reason = reason
        self._state.triggered_at = datetime.now(timezone.utc).isoformat()
        entry = {"reason": reason, "at": self._state.triggered_at}
        if detail:
            entry.update(detail)
        self._state.triggers.append(entry)
        logger.critical("PILOT_KILL_SWITCH: %s", reason)

    def check_daily_loss(self, daily_loss_pct: float, limit: float) -> bool:
        if daily_loss_pct >= limit:
            self.trigger("daily_loss_exceeded", detail={"daily_loss_pct": daily_loss_pct, "limit": limit})
            return True
        return False

    def check_connection(self, connected: bool) -> bool:
        if not connected:
            self.trigger("connection_failure")
            return True
        return False

    def check_spread(self, spread_pips: float, max_spread: float) -> bool:
        if spread_pips > max_spread:
            self.trigger("abnormal_spread", detail={"spread_pips": spread_pips, "max": max_spread})
            return True
        return False

    def check_execution_failures(self, failures: int, threshold: int = 3) -> bool:
        if failures >= threshold:
            self.trigger("repeated_execution_failure", detail={"failures": failures})
            return True
        return False

    def check_checksum(self, valid: bool) -> bool:
        if not valid:
            self.trigger("model_checksum_mismatch")
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self._state.active,
            "reason": self._state.reason,
            "triggered_at": self._state.triggered_at,
            "triggers": list(self._state.triggers),
        }

    def reset_for_tests(self) -> None:
        self._state = KillSwitchState()
