"""Phase 12 — pre-order safety orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from tradingbot.domain.models import TradingSignal
from tradingbot.ml.live_pilot.config import PilotConfig, is_pilot_live_enabled
from tradingbot.ml.live_pilot.kill_switch import PilotKillSwitch
from tradingbot.ml.live_pilot.position_limiter import PositionLimiter

logger = logging.getLogger(__name__)


@dataclass
class SafetyCheckResult:
    allowed: bool
    reason: str = ""
    checks: dict[str, bool] = field(default_factory=dict)


class SafetyManager:
    """Gate every order through model, risk, position, kill-switch, and pilot approval."""

    def __init__(
        self,
        config: PilotConfig,
        *,
        kill_switch: PilotKillSwitch | None = None,
        position_limiter: PositionLimiter | None = None,
        model_checksum_valid: bool = True,
    ) -> None:
        self.config = config
        self.kill_switch = kill_switch or PilotKillSwitch()
        self.position_limiter = position_limiter or PositionLimiter(
            max_open_positions=config.max_open_positions,
            max_trades_per_day=config.max_trades_per_day,
            max_consecutive_losses=config.max_consecutive_losses,
        )
        self.model_checksum_valid = model_checksum_valid
        self._execution_failures = 0
        self._stats = {"allowed": 0, "blocked": 0, "reasons": {}}

    def validate_pre_order(
        self,
        signal: TradingSignal,
        *,
        lot: float,
        spread_pips: float | None = None,
        mt5_connected: bool = True,
        regime: str | None = None,
        daily_loss_pct: float = 0.0,
    ) -> SafetyCheckResult:
        checks: dict[str, bool] = {}
        mode = self.config.mode.upper()

        checks["model_checksum"] = self.model_checksum_valid
        if not self.model_checksum_valid:
            self.kill_switch.check_checksum(False)
            return self._block("model_checksum_invalid", checks)

        if self.kill_switch.active:
            return self._block(f"kill_switch:{self.kill_switch.reason}", checks)

        if mode == "PILOT" and not is_pilot_live_enabled():
            return self._block("pilot_not_approved", checks)

        if mode in ("SHADOW", "PAPER"):
            return self._block(f"mode_{mode.lower()}_no_live_orders", checks)

        if not mt5_connected:
            self.kill_switch.check_connection(False)
            return self._block("mt5_not_connected", checks)

        if spread_pips is not None and spread_pips > self.config.max_spread_pips:
            self.kill_switch.check_spread(spread_pips, self.config.max_spread_pips)
            return self._block("spread_too_high", checks)

        self.kill_switch.check_daily_loss(daily_loss_pct, self.config.max_daily_loss_pct)
        if self.kill_switch.active:
            return self._block("daily_loss_limit", checks)

        ok, reason = self.position_limiter.can_open_position()
        checks["position_limit"] = ok
        if not ok:
            self.position_limiter.reject(reason)
            return self._block(reason, checks)

        if signal.stop_loss is None or signal.take_profit is None:
            return self._block("invalid_sl_tp", checks)

        if lot <= 0:
            return self._block("invalid_volume", checks)

        if regime is not None:
            allowed_regime = regime in self.config.allowed_regimes
            checks["regime_allowed"] = allowed_regime
            if self.config.regime_filter_block and not allowed_regime:
                return self._block(f"regime_blocked:{regime}", checks)

        checks["all_passed"] = True
        self._stats["allowed"] += 1
        return SafetyCheckResult(allowed=True, reason="ok", checks=checks)

    def record_execution_failure(self) -> None:
        self._execution_failures += 1
        self.kill_switch.check_execution_failures(self._execution_failures)

    def record_execution_success(self) -> None:
        self._execution_failures = 0

    def _block(self, reason: str, checks: dict[str, bool]) -> SafetyCheckResult:
        self._stats["blocked"] += 1
        self._stats["reasons"][reason] = self._stats["reasons"].get(reason, 0) + 1
        logger.info("SAFETY_BLOCKED: %s", reason)
        return SafetyCheckResult(allowed=False, reason=reason, checks=checks)

    def summary(self) -> dict[str, Any]:
        return {
            "allowed": self._stats["allowed"],
            "blocked": self._stats["blocked"],
            "block_reasons": dict(self._stats["reasons"]),
            "kill_switch": self.kill_switch.to_dict(),
            "position_limiter": self.position_limiter.to_dict(),
        }
