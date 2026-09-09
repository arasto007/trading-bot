"""Regression - engine telemetry must not deadlock on nested lock acquisition."""

from __future__ import annotations

import tradingbot.services.engine_telemetry as et
from tradingbot.services.engine_telemetry import ENGINE_PA, EngineTelemetryService


def test_record_rejection_consecutive_alert_no_deadlock(tmp_path):
    """20+ rejections must emit alert without re-entering threading.Lock."""
    old_instance = et._instance
    try:
        et._instance = EngineTelemetryService(tmp_path)
        tel = et.get_engine_telemetry(tmp_path)
        for i in range(21):
            tel.record_rejection(ENGINE_PA, reason=f"reject_{i}")
        alerts = tel._read_jsonl(tel._alerts_path)
        assert any(a.get("alert") == "consecutive_rejects" for a in alerts)
    finally:
        et._instance = old_instance
