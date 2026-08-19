"""
سرویس‌های پس‌زمینه — مدیریتِ start/stop برای PositionProtector + PositionRecoveryService.

هر دو سرویس مستقل از pipeline اصلی کار می‌کنند (trailing stop، محافظت، بازیابی پس از
restart) و اکنون در پکیج محلی `tradingbot.services` زندگی می‌کنند (بدون وابستگی به engine).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.mt5_utils import get_mt5_credentials
from tradingbot.infra.logging import get_logger
from tradingbot.services.position_protector import PositionProtector
from tradingbot.services.position_recovery_service import PositionRecoveryService

logger = logging.getLogger(__name__)


def build_mt5_credentials(config: dict[str, Any]) -> dict[str, Any]:
    login, password, server = get_mt5_credentials(config)
    return {"login": login, "password": password, "server": server}


class BackgroundServices:
    """مدیریت start/stop سرویس‌های پس‌زمینه (protector + recovery)."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        enable_protector: bool = True,
        enable_recovery: bool = True,
    ) -> None:
        self._config = config or load_legacy_config()
        base_dir = self._config.get("BASE_DIR", ".")
        self._logger = get_logger("background_services", base_dir)
        self._enable_protector = enable_protector
        self._enable_recovery = enable_recovery

        creds = build_mt5_credentials(self._config)

        self._protector: PositionProtector | None = None
        self._protector_thread: threading.Thread | None = None
        if enable_protector:
            protector_config = {
                "position_check_interval": self._config.get("position_check_interval", 10),
                "trailing_stop": self._config.get("trailing_stop", {}),
                "max_position_age_hours": self._config.get("max_position_age_hours", 24),
                "emergency_drawdown": self._config.get("emergency_drawdown", 0.25),
                "mt5_credentials": creds,
            }
            self._protector = PositionProtector(protector_config, self._logger)

        self._recovery: PositionRecoveryService | None = None
        if enable_recovery:
            recovery_config = {
                "BASE_DIR": base_dir,
                "position_check_interval": self._config.get("position_check_interval", 10),
                "max_position_age_hours": self._config.get("max_position_age_hours", 48),
                "trailing_stop_atr_multiplier": self._config.get(
                    "trailing_stop_atr_multiplier", 2.0
                ),
                "trailing_stop_enabled": True,
                "emergency_drawdown": self._config.get("emergency_drawdown", 0.25),
                "emergency_position_loss": 0.15,
                "mt5_credentials": creds,
            }
            self._recovery = PositionRecoveryService(recovery_config, self._logger)

    @property
    def protector(self) -> Any:
        return self._protector

    @property
    def recovery(self) -> Any:
        return self._recovery

    def start_all(self) -> None:
        if self._recovery is not None:
            try:
                if self._recovery.start():
                    logger.info("Recovery service started")
                else:
                    logger.warning("Recovery service failed to start")
            except Exception as e:  # noqa: BLE001
                logger.error("Recovery start error: %s", e)

        if self._protector is not None:
            try:
                self._protector_thread = threading.Thread(
                    target=self._protector.run, daemon=True
                )
                self._protector_thread.start()
                logger.info("Position protector thread started")
            except Exception as e:  # noqa: BLE001
                logger.error("Protector start error: %s", e)

    def stop_all(self) -> None:
        if self._protector is not None:
            try:
                self._protector.stop()
            except Exception as e:  # noqa: BLE001
                logger.debug("Protector stop error: %s", e)
        if self._protector_thread is not None:
            self._protector_thread.join(timeout=5)

        if self._recovery is not None:
            try:
                self._recovery.stop()
            except Exception as e:  # noqa: BLE001
                logger.debug("Recovery stop error: %s", e)

        logger.info("Background services stopped")
