"""Phase 21D — Meta false-negative capture + 24-bar joiner."""
from __future__ import annotations

import json

from tradingbot.adapters.risk_gate import apply_pa_meta_decision
from tradingbot.services.meta_false_negative import classify_24_bar_outcome, summarize_outcomes


def test_apply_pa_meta_decision_still_rejects():
    should_reject, would_reject, label = apply_pa_meta_decision(
        prob=0.27, threshold=0.33, gating=True, observer_mode=False
    )
    assert should_reject is True
    assert would_reject is True
    assert label == "rejected"
    observer_reject, observer_would, _ = apply_pa_meta_decision(
        prob=0.27, threshold=0.33, gating=True, observer_mode=True
    )
    assert observer_reject is False
    assert observer_would is True


def test_fn_logger_writes_required_keys(tmp_path, monkeypatch):
    from tradingbot.services import jsonl_rotation as jr
    from tradingbot.services import meta_decision_log as mdl

    path = tmp_path / "meta_false_negative_candidates.jsonl"
    monkeypatch.setattr(mdl, "FALSE_NEGATIVE_PATH", path)
    jr._handlers.clear()
    mdl.log_meta_false_negative_candidate(
        timestamp="2026-08-10T15:00:00+00:00",
        symbol="XAUUSD_i",
        direction="BUY",
        meta_score=0.27,
        threshold=0.33,
        features={"confidence": 0.6, "rr": 1.8},
        entry=2400.0,
        stop_loss=2395.0,
        take_profit=2410.0,
        timeframe="M5",
    )
    assert path.is_file()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    for key in (
        "timestamp",
        "symbol",
        "direction",
        "meta_score",
        "threshold",
        "setup_snapshot_id",
        "features",
    ):
        assert key in row
    assert row["symbol"] == "XAUUSD_i"
    assert row["direction"] == "BUY"
    assert row["meta_score"] == 0.27
    assert row["threshold"] == 0.33
    assert row["features"]["confidence"] == 0.6
    assert row["setup_snapshot_id"]


def test_classify_mfe_1r_timeout():
    # BUY: +1.2R high on bar 2, never hits SL, never 1.5R
    high = [2400.0, 2400.0, 2406.0] + [2401.0] * 24
    low = [2399.0, 2399.5, 2399.8] + [2399.5] * 24
    out = classify_24_bar_outcome(high, low, 0, 1, 2400.0, 2395.0, len(high))
    assert out["reached_1r"] is True
    assert out["reached_15r"] is False
    assert out["outcome"] == "plus_1r"


def test_classify_mfe_15r():
    high = [2400.0, 2408.0] + [2401.0] * 24
    low = [2399.0, 2399.5] + [2399.5] * 24
    out = classify_24_bar_outcome(high, low, 0, 1, 2400.0, 2395.0, len(high))
    assert out["reached_1r"] is True
    assert out["reached_15r"] is True
    assert out["outcome"] == "plus_1_5r"


def test_classify_sl_first():
    high = [2400.0, 2401.0] + [2401.0] * 24
    low = [2399.0, 2394.0] + [2399.0] * 24
    out = classify_24_bar_outcome(high, low, 0, 1, 2400.0, 2395.0, len(high))
    assert out["reached_1r"] is False
    assert out["outcome"] == "sl_first"


def test_classify_timeout():
    high = [2400.0] + [2402.0] * 25
    low = [2399.0] + [2398.0] * 25
    out = classify_24_bar_outcome(high, low, 0, 1, 2400.0, 2395.0, len(high))
    assert out["reached_1r"] is False
    assert out["sl_hit"] is False
    assert out["outcome"] == "timeout"


def test_classify_sell_1r():
    high = [2400.0, 2401.0] + [2399.0] * 24
    low = [2399.0, 2394.0] + [2398.0] * 24
    out = classify_24_bar_outcome(high, low, 0, -1, 2400.0, 2405.0, len(high))
    assert out["reached_1r"] is True
    assert out["outcome"] == "plus_1r"


def test_summarize_fn_rate():
    rows = [
        {"reached_1r": True, "reached_15r": True, "outcome": "plus_1_5r", "mfe_r": 1.7},
        {"reached_1r": True, "reached_15r": False, "outcome": "plus_1r", "mfe_r": 1.2},
        {"reached_1r": False, "reached_15r": False, "outcome": "sl_first", "mfe_r": 0.2},
        {"reached_1r": False, "reached_15r": False, "outcome": "timeout", "mfe_r": 0.4},
    ]
    stats = summarize_outcomes(rows)
    assert stats["candidates"] == 4
    assert stats["became_1r"] == 2
    assert stats["became_15r"] == 1
    assert stats["sl_first"] == 1
    assert stats["timeout"] == 1
    assert stats["false_negative_rate"] == 0.5
    assert stats["potential_recoverable_r"] == 2.5