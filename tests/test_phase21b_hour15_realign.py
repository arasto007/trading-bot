"""Phase 21B — M5 hour-15 window helpers (gold_ny_sweep only)."""
from __future__ import annotations

from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.filter_policy import aligned_session_hours
from tradingbot.domain.gold_strategies.m5_london_sweep import (
    m5_asian_end_hour,
    m5_hour15_telemetry,
    m5_ny_entry_hours,
)


def test_m5_preset_hour15_and_asian_8():
    cfg = get_price_action_config("XAUUSD", "M5")
    assert cfg["PRESET"] == "gold_ny_sweep"
    assert m5_ny_entry_hours(cfg) == (15, 16)
    assert m5_asian_end_hour(cfg) == 8
    tel = m5_hour15_telemetry(cfg)
    assert tel["hour15_mode"] is True
    assert tel["asian_end_utc"] == 8


def test_m15_h4_windows_untouched():
    m15 = get_price_action_config("XAUUSD", "M15")
    h4 = get_price_action_config("XAUUSD", "H4")
    assert m15["SESSION_START_HOUR"] == 7
    assert h4["SESSION_START_HOUR"] == 0
    assert "NY_ENTRY_START_UTC" not in m15
    assert "NY_ENTRY_START_UTC" not in h4


def test_aligned_session_hours_uses_utc_keys():
    start, end = aligned_session_hours(get_price_action_config("XAUUSD", "M5"))
    assert (start, end) == (15, 16)


def test_utc_keys_override_hour_keys():
    cfg = {
        "NY_ENTRY_START_HOUR": 10,
        "NY_ENTRY_END_HOUR": 17,
        "NY_ENTRY_START_UTC": 15,
        "NY_ENTRY_END_UTC": 16,
        "ASIAN_END_HOUR": 7,
        "ASIAN_SESSION_END_UTC": 8,
    }
    assert m5_ny_entry_hours(cfg) == (15, 16)
    assert m5_asian_end_hour(cfg) == 8