"""Tests for demo session filter override."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_session_filter_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DEMO_DISABLE_SESSION_FILTER", raising=False)
    from tradingbot.domain import filter_policy

    filter_policy._DEMO_SESSION_DISABLED = False
    assert filter_policy.is_session_filter_enabled() is True
    assert filter_policy.demo_session_override_active() is False


def test_session_filter_disabled_for_demo(monkeypatch):
    monkeypatch.setenv("DEMO_DISABLE_SESSION_FILTER", "true")
    from tradingbot.domain import filter_policy

    filter_policy._DEMO_SESSION_DISABLED = True
    assert filter_policy.is_session_filter_enabled() is False
    assert filter_policy.demo_session_override_active() is True


def test_demo_note_line_when_disabled(monkeypatch):
    monkeypatch.setenv("DEMO_DISABLE_SESSION_FILTER", "true")
    from tradingbot.domain import filter_policy

    filter_policy._DEMO_SESSION_DISABLED = True
    spec = importlib.util.spec_from_file_location(
        "status_snapshot",
        Path(__file__).resolve().parents[1] / "scripts" / "status_snapshot.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    note = mod._demo_note_line()
    assert note is not None
    assert "session filter DISABLED" in note
