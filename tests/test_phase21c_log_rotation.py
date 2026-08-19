"""Phase 21C — rotating JSONL + 20min heartbeat freshness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from tradingbot.services import jsonl_rotation as jr
from tradingbot.services.jsonl_rotation import MAX_BYTES, BACKUP_COUNT, rotation_active
from tradingbot.services.live_loop_health import evaluate_heartbeat_freshness
from tradingbot.services.rejection_events import log_rejection_event, set_rejection_logging_enabled
from tradingbot.services.router_decision_log import append_router_decision


PRE_NY = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


def test_rotation_handler_settings(tmp_path):
    path = tmp_path / "rejection_events.jsonl"
    jr._handlers.clear()
    h = jr.rotating_handler(path)
    assert isinstance(h, RotatingFileHandler)
    assert h.maxBytes == MAX_BYTES
    assert h.backupCount == BACKUP_COUNT
    assert rotation_active(path) is True


def test_rotation_rolls_file(tmp_path, monkeypatch):
    monkeypatch.setattr(jr, "MAX_BYTES", 400)
    jr._handlers.clear()
    path = tmp_path / "router_decisions.jsonl"
    for i in range(80):
        jr.append_rotating_jsonl(path, {"i": i, "pad": "x" * 40})
    names = sorted(p.name for p in tmp_path.glob("router_decisions.jsonl*"))
    assert "router_decisions.jsonl" in names
    assert any(n.endswith(".1") or ".1" in n for n in names)


def test_rejection_and_router_use_rotator(tmp_path, monkeypatch):
    rej = tmp_path / "rejection_events.jsonl"
    router = tmp_path / "router_decisions.jsonl"
    monkeypatch.setenv("TRADINGBOT_REJECTION_LOG", str(rej))
    monkeypatch.setenv("ROUTER_DECISION_LOG", str(router))
    jr._handlers.clear()
    set_rejection_logging_enabled(True)
    log_rejection_event(stage="TEST", reason="unit", symbol="XAUUSD")
    append_router_decision({"selected_engine": "PA", "rejection_reason": ""})
    assert rej.is_file() and rej.read_text(encoding="utf-8").strip()
    assert router.is_file() and router.read_text(encoding="utf-8").strip()


def test_freshness_under_20min_no_restart():
    now = PRE_NY
    hb = {"timestamp_utc": (now - timedelta(minutes=19)).isoformat()}
    d = evaluate_heartbeat_freshness(
        now=now, heartbeat=hb, child_started_at=now - timedelta(hours=1), already_restarted=False
    )
    assert d.stalled is False
    assert d.should_restart is False