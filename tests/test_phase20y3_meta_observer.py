"""Phase 20Y-3 — Meta observer demotion: score+log, no decision gating."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from tradingbot.adapters.risk_gate import (
    apply_pa_meta_decision,
    meta_observer_mode_enabled,
    _stamp_meta_observer_fields,
)
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import TradingSignal
from tradingbot.services import meta_decision_log as mdl


def test_observer_flag_respects_config():
    assert meta_observer_mode_enabled({"META_OBSERVER_MODE": True}) is True
    assert meta_observer_mode_enabled({"META_OBSERVER_MODE": False}) is False


def test_observer_never_rejects_low_score():
    reject, would, label = apply_pa_meta_decision(
        prob=0.21, threshold=0.33, gating=True, observer_mode=True
    )
    assert reject is False
    assert would is True
    assert label == "observer_would_reject"


def test_observer_high_score_would_not_reject():
    reject, would, label = apply_pa_meta_decision(
        prob=0.80, threshold=0.33, gating=True, observer_mode=True
    )
    assert reject is False
    assert would is False
    assert label == "approved"


def test_gate_mode_still_rejects():
    reject, would, label = apply_pa_meta_decision(
        prob=0.21, threshold=0.33, gating=True, observer_mode=False
    )
    assert reject is True
    assert would is True
    assert label == "rejected"


def test_skip_regime_no_live_reject_but_would_reject_is_true():
    reject, would, label = apply_pa_meta_decision(
        prob=0.21, threshold=0.33, gating=False, observer_mode=False
    )
    assert reject is False
    assert would is True
    assert label == "approved"


def test_stamp_required_telemetry_fields():
    sig = TradingSignal(
        direction=SignalDirection.BUY,
        confidence=0.7,
        symbol="XAUUSD",
        timeframe="M5",
        strategy_name="priceaction",
        created_at=datetime.now(timezone.utc),
        metadata={},
    )
    _stamp_meta_observer_fields(
        sig,
        meta_score=0.21,
        meta_threshold=0.33,
        meta_would_reject=True,
        meta_observer_mode=True,
    )
    assert sig.metadata["meta_score"] == 0.21
    assert sig.metadata["meta_threshold"] == 0.33
    assert sig.metadata["meta_would_reject"] is True
    assert sig.metadata["meta_observer_mode"] is True


def test_observer_jsonl_written(tmp_path, monkeypatch):
    path = tmp_path / "meta_observer_events.jsonl"
    monkeypatch.setattr(mdl, "OBSERVER_LOG_PATH", path)
    mdl.log_meta_observer_event(
        symbol="XAUUSD",
        timeframe="M5",
        meta_score=0.21,
        meta_threshold=0.33,
        meta_would_reject=True,
        meta_observer_mode=True,
        signal_direction="SELL",
        gating=True,
        rejected=False,
        reason="meta observer would reject",
    )
    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["meta_score"] == 0.21
    assert row["meta_threshold"] == 0.33
    assert row["meta_would_reject"] is True
    assert row["meta_observer_mode"] is True
    assert row["rejected"] is False