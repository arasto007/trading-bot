"""Phase 20A — hard safety monitor with instant stop triggers."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.live_pilot.config import PilotConfig
from tradingbot.ml.live_pilot.kill_switch import PilotKillSwitch
from tradingbot.ml.live_pilot.position_limiter import PositionLimiter
from tradingbot.ml.live_pilot.safety_manager import SafetyManager
from tradingbot.ml.phase20a.config import (
    EXECUTION_FAILURE_SPIKE,
    LATENCY_P95_LIMIT_MS,
    LATENCY_SUSTAINED_CYCLES,
    MAX_SIGNALS_PER_HOUR,
    SHORT_WINDOW_DD_PCT,
    DeploymentConfig,
)
from tradingbot.ml.phase20a.rollback import execute_rollback

logger = logging.getLogger(__name__)


@dataclass
class SafetyState:
    signals_this_hour: int = 0
    hour_key: str = ""
    execution_failures: int = 0
    latency_high_streak: int = 0
    peak_equity: float = 0.0
    rollback_triggered: bool = False


class Phase20aSafetyMonitor:
    """Enforces Phase 20A hard safety rules — triggers rollback on breach."""

    def __init__(self, config: DeploymentConfig) -> None:
        self.config = config
        self.kill_switch = PilotKillSwitch()
        self.position_limiter = PositionLimiter(
            max_open_positions=config.max_open_positions,
            max_trades_per_day=config.max_trades_per_day,
            max_consecutive_losses=config.max_consecutive_losses,
        )
        pilot_cfg = PilotConfig(
            symbol=config.symbol,
            timeframe=config.timeframe,
            mode="PILOT",
            risk_pct=config.risk_pct,
            max_open_positions=config.max_open_positions,
            max_trades_per_day=config.max_trades_per_day,
            max_consecutive_losses=config.max_consecutive_losses,
            max_spread_pips=config.max_spread_pips,
        )
        self.pilot_safety = SafetyManager(
            pilot_cfg,
            kill_switch=self.kill_switch,
            position_limiter=self.position_limiter,
            model_checksum_valid=True,
        )
        self._state = SafetyState()
        self._latency_samples: deque[float] = deque(maxlen=200)
        self._events: list[dict[str, Any]] = []

    def record_signal(self) -> None:
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        if hour != self._state.hour_key:
            self._state.hour_key = hour
            self._state.signals_this_hour = 0
        self._state.signals_this_hour += 1
        if self._state.signals_this_hour > MAX_SIGNALS_PER_HOUR:
            self._trigger("signal_explosion", {"signals_this_hour": self._state.signals_this_hour})

    def record_execution_failure(self) -> None:
        self._state.execution_failures += 1
        self.kill_switch.check_execution_failures(self._state.execution_failures, EXECUTION_FAILURE_SPIKE)
        if self._state.execution_failures >= EXECUTION_FAILURE_SPIKE:
            self._trigger("execution_failure_spike", {"failures": self._state.execution_failures})

    def record_execution_success(self) -> None:
        self._state.execution_failures = 0

    def record_latency(self, latency_ms: float) -> None:
        self._latency_samples.append(latency_ms)
        if latency_ms > LATENCY_P95_LIMIT_MS:
            self._state.latency_high_streak += 1
        else:
            self._state.latency_high_streak = 0
        if self._state.latency_high_streak >= LATENCY_SUSTAINED_CYCLES:
            self._trigger(
                "latency_p95_exceeded",
                {"latency_ms": latency_ms, "streak": self._state.latency_high_streak},
            )

    def record_equity(self, equity: float) -> None:
        if equity <= 0:
            return
        self._state.peak_equity = max(self._state.peak_equity, equity)
        if self._state.peak_equity > 0:
            dd = (self._state.peak_equity - equity) / self._state.peak_equity
            if dd >= SHORT_WINDOW_DD_PCT:
                self._trigger("drawdown_short_window", {"drawdown_pct": round(dd * 100, 2)})

    def record_risk_anomaly(self, reason: str) -> None:
        self._trigger("riskgate_anomaly", {"reason": reason})

    def record_engine_divergence(self, detail: dict[str, Any]) -> None:
        self._trigger("engine_divergence", detail)

    def _trigger(self, reason: str, detail: dict[str, Any] | None = None) -> None:
        self.kill_switch.trigger(reason, detail=detail)
        self._events.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "detail": detail or {},
        })
        if not self._state.rollback_triggered:
            self._state.rollback_triggered = True
            rb = execute_rollback(reason=reason)
            logger.critical("PHASE20A_ROLLBACK: %s | %s", reason, rb)

    @property
    def should_stop(self) -> bool:
        return self.kill_switch.active or self._state.rollback_triggered

    def summary(self) -> dict[str, Any]:
        values = sorted(self._latency_samples)
        p95 = values[int(len(values) * 0.95)] if values else 0.0
        return {
            "kill_switch": self.kill_switch.to_dict(),
            "position_limiter": self.position_limiter.to_dict(),
            "signals_this_hour": self._state.signals_this_hour,
            "execution_failures": self._state.execution_failures,
            "latency_p95_ms": round(p95, 2),
            "latency_high_streak": self._state.latency_high_streak,
            "rollback_triggered": self._state.rollback_triggered,
            "events": self._events[-50:],
        }
