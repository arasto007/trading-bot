"""Background Phase-2 ops: daily report + periodic reconciliation."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from tradingbot.services.drift_monitor import compute_drift_report, format_drift_telegram
from tradingbot.services.live_reporting import build_daily_report, format_daily_report_telegram
from tradingbot.services.notifier import Notifier

logger = logging.getLogger(__name__)


class LiveOpsService:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        base_dir = config.get("BASE_DIR", ".")
        self._notifier = Notifier(base_dir)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_daily: str | None = None
        self._last_drift: str | None = None
        self._report_hour_utc = int(os.getenv("LIVE_DAILY_REPORT_HOUR_UTC", "20"))
        self._drift_hour_utc = int(os.getenv("LIVE_DRIFT_CHECK_HOUR_UTC", "21"))
        self._telegram_enabled = bool(
            os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip()
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="LiveOpsService", daemon=True)
        self._thread.start()
        logger.info(
            "LiveOpsService started | daily_report_hour_utc=%s drift_check_hour_utc=%s telegram=%s",
            self._report_hour_utc,
            self._drift_hour_utc,
            "on" if self._telegram_enabled else "off (optional)",
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def run_daily_report_now(self) -> dict[str, Any]:
        report = build_daily_report(self._config.get("BASE_DIR", "."), self._config)
        text = format_daily_report_telegram(report)
        self._notifier.alert("info", text)
        if not self._telegram_enabled:
            logger.debug("Daily report logged locally (Telegram not configured)")
        try:
            from tradingbot.services.phase47c_forward_tracker import is_phase47c_enabled, run_daily_rollup

            if is_phase47c_enabled():
                run_daily_rollup(self._config)
        except Exception as exc:
            logger.warning("Phase47C daily rollup failed: %s", exc)
        try:
            from tradingbot.services.phase51a_forward_cert import is_phase51a_enabled, run_daily_rollup as run_51a

            if is_phase51a_enabled():
                run_51a(self._config)
        except Exception as exc:
            logger.warning("Phase51A daily rollup failed: %s", exc)
        try:
            from tradingbot.services.daily_engine_report import run_daily_engine_report

            run_daily_engine_report(self._config.get("BASE_DIR"))
        except Exception as exc:
            logger.warning("Engine daily report failed: %s", exc)
        return report

    def run_drift_check_now(self, *, notify: bool = True) -> dict[str, Any]:
        report = compute_drift_report(self._config.get("BASE_DIR", "."), self._config)
        status = str(report.get("status", "unknown"))
        if notify and status in ("warn", "critical"):
            level = "critical" if status == "critical" else "warn"
            self._notifier.alert(level, format_drift_telegram(report))
            if not self._telegram_enabled:
                logger.debug("Drift alert logged locally (Telegram not configured)")
        return report

    def _loop(self) -> None:
        while not self._stop.wait(120):
            try:
                now = datetime.now(timezone.utc)
                day_key = now.strftime("%Y-%m-%d")
                if now.hour >= self._report_hour_utc and self._last_daily != day_key:
                    self.run_daily_report_now()
                    self._last_daily = day_key
                if now.hour >= self._drift_hour_utc and self._last_drift != day_key:
                    self.run_drift_check_now()
                    self._last_drift = day_key
            except Exception as exc:
                logger.warning("LiveOpsService loop error: %s", exc)
