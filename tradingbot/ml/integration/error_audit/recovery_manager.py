"""Phase 10.5 — recoverable shadow cycle error handling."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from tradingbot.ml.integration.error_audit.kernel_error_analyzer import split_kernel_errors

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class RecoveryState:
    cycles_attempted: int = 0
    cycles_completed: int = 0
    recoverable_failures: int = 0
    fatal_failures: int = 0
    failure_log: list[dict[str, Any]] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        if self.cycles_attempted == 0:
            return 1.0
        return self.cycles_completed / self.cycles_attempted

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_attempted": self.cycles_attempted,
            "cycles_completed": self.cycles_completed,
            "completion_rate": round(self.completion_rate, 4),
            "recoverable_failures": self.recoverable_failures,
            "fatal_failures": self.fatal_failures,
            "failure_log": self.failure_log,
        }


class ShadowRecoveryManager:
    """
    Continue shadow runs after recoverable errors.

    RiskGate blocks are NOT failures. Stage exceptions are logged and skipped.
    """

    def __init__(self) -> None:
        self.state = RecoveryState()

    def classify_context_errors(self, errors: list[str]) -> tuple[list[str], list[str]]:
        return split_kernel_errors(errors)

    def run_cycle(self, fn: Callable[[], T], *, timestamp: str, bar_index: int) -> T | None:
        self.state.cycles_attempted += 1
        try:
            result = fn()
            self.state.cycles_completed += 1
            return result
        except Exception as exc:
            self.state.recoverable_failures += 1
            entry = {
                "timestamp": timestamp,
                "bar_index": bar_index,
                "exception": type(exc).__name__,
                "message": str(exc),
                "recoverable": True,
            }
            self.state.failure_log.append(entry)
            logger.warning("Shadow cycle recovered after error at %s: %s", timestamp, exc)
            return None

    def record_fatal(self, *, timestamp: str, message: str) -> None:
        self.state.fatal_failures += 1
        self.state.failure_log.append(
            {"timestamp": timestamp, "message": message, "recoverable": False}
        )
