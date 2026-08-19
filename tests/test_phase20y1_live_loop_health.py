"""Phase 20Y-1 live loop health — stall detector, heartbeat, router counter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradingbot.services import live_loop_health as llh
from tradingbot.services.live_loop_health import (
    evaluate_heartbeat_freshness,
    evaluate_ny_stall,
    record_router_activity,
    write_healthcheck_heartbeat,
    write_heartbeat,
)


NY = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
PRE_NY = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)


def test_outside_ny_never_stalls():
    d = evaluate_ny_stall(now=PRE_NY, heartbeat=None, child_started_at=PRE_NY - timedelta(hours=2))
    assert d.stalled is False
    assert d.should_restart is False
    assert d.reason == "outside_ny_window"


def test_fresh_heartbeat_in_ny_ok():
    hb = {
        "timestamp_utc": NY.isoformat(),
        "last_bar_time_utc": (NY - timedelta(minutes=4)).isoformat(),
        "loop_iteration": 10,
        "router_alive": True,
        "kernel_alive": True,
        "mt5_connected": True,
    }
    d = evaluate_ny_stall(now=NY, heartbeat=hb, child_started_at=NY - timedelta(minutes=30))
    assert d.stalled is False
    assert d.should_restart is False


def test_stale_heartbeat_restarts_once():
    started = NY - timedelta(minutes=25)
    stale = {
        "timestamp_utc": (NY - timedelta(minutes=21)).isoformat(),
        "last_bar_time_utc": (NY - timedelta(minutes=4)).isoformat(),
    }
    d = evaluate_ny_stall(now=NY, heartbeat=stale, child_started_at=started, already_restarted=False)
    assert d.stalled is True
    assert d.should_restart is True
    assert "heartbeat_stale" in d.reason
    d2 = evaluate_ny_stall(now=NY, heartbeat=stale, child_started_at=started, already_restarted=True)
    assert d2.stalled is True
    assert d2.should_restart is False


def test_bar_lag_three_m5_candles():
    started = NY - timedelta(minutes=30)
    hb = {
        "timestamp_utc": NY.isoformat(),
        "last_bar_time_utc": (NY - timedelta(minutes=16)).isoformat(),
    }
    d = evaluate_ny_stall(now=NY, heartbeat=hb, child_started_at=started)
    assert d.stalled is True
    assert "last_bar_lag" in d.reason
    assert d.should_restart is True


def test_missing_heartbeat_grace_under_20min():
    started = NY - timedelta(minutes=5)
    d = evaluate_ny_stall(now=NY, heartbeat=None, child_started_at=started)
    assert d.stalled is False


def test_healthcheck_writes_without_mt5(tmp_path, monkeypatch):
    monkeypatch.setattr(llh, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(llh, "HEARTBEAT_PATH", tmp_path / "live_heartbeat.json")
    path = write_healthcheck_heartbeat()
    assert path.is_file()
    import json
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["mt5_connected"] is False
    assert row["kernel_alive"] is False
    assert "timestamp_utc" in row
    assert "loop_iteration" in row


def test_router_activity_rolls_date(tmp_path, monkeypatch):
    monkeypatch.setattr(llh, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(llh, "ROUTER_ACTIVITY_PATH", tmp_path / "router_activity_today.json")
    record_router_activity(pa_hold=True, selected_engine_none=True)
    record_router_activity(pa_signal=True)
    import json
    row = json.loads((tmp_path / "router_activity_today.json").read_text(encoding="utf-8"))
    assert row["router_calls"] == 2
    assert row["pa_hold"] == 1
    assert row["pa_signal"] == 1
    assert row["selected_engine_none"] == 1
    assert row["date"]


def test_heartbeat_freshness_20min_one_restart_then_alert():
    now = PRE_NY
    started = now - timedelta(minutes=30)
    stale = {"timestamp_utc": (now - timedelta(minutes=21)).isoformat()}
    d = evaluate_heartbeat_freshness(
        now=now, heartbeat=stale, child_started_at=started, already_restarted=False
    )
    assert d.stalled is True
    assert d.should_restart is True
    d2 = evaluate_heartbeat_freshness(
        now=now, heartbeat=stale, child_started_at=started, already_restarted=True
    )
    assert d2.stalled is True
    assert d2.should_restart is False