"""Phase 22C — hold chain and config tests."""

from __future__ import annotations

import pytest

from tradingbot.ml.research.phase22c.config import compute_daily_loss_budget, load_phase22c_config
from tradingbot.ml.research.phase22c.hold_chain import HoldStage, get_hold_chain, reset_hold_chain


def test_hold_chain_exact_counters():
    reset_hold_chain()
    chain = get_hold_chain()
    chain.record_bar()
    chain.record(HoldStage.DECISION)
    chain.record_bar()
    chain.record(HoldStage.CALIBRATION)
    chain.record_buy()
    snap = chain.snapshot()
    assert snap["bars_evaluated"] == 2
    assert snap["ml_hold_stages"]["decision_hold"] == 1
    assert snap["ml_hold_stages"]["calibration_hold"] == 1
    assert snap["buy_emitted"] == 1
    assert snap["sell_emitted"] == 0


def test_daily_loss_budget_proportional_floor():
    budget = compute_daily_loss_budget(
        reference_balance=200.0,
        max_daily_loss_pct=0.04,
        risk_per_trade=0.005,
        floor_trades=3,
    )
    assert budget >= 200.0 * 0.04
    assert budget >= 200.0 * 0.005 * 3


def test_phase22c_config_from_env(monkeypatch):
    monkeypatch.setenv("PHASE22C_ENABLED", "true")
    monkeypatch.setenv("PHASE22C_RANGE_BUY_THRESHOLD", "0.51")
    monkeypatch.setenv("PHASE22C_RANGE_SELL_THRESHOLD", "0.49")
    cfg = load_phase22c_config()
    assert cfg.enabled is True
    assert cfg.range_buy_threshold == 0.51
    assert cfg.range_sell_threshold == 0.49


def test_symmetric_thresholds_reduce_sell_only_skew():
    from tradingbot.ml.paper_trading.signal_engine import SignalConfig, SignalEngine

    asymmetric = SignalEngine(SignalConfig(buy_threshold=0.55, sell_threshold=0.45))
    symmetric = SignalEngine(SignalConfig(buy_threshold=0.52, sell_threshold=0.48))
    probs = [0.50, 0.51, 0.52, 0.48, 0.47]
    asym_buy = sum(1 for p in probs if asymmetric.generate(p).value == "BUY")
    sym_buy = sum(1 for p in probs if symmetric.generate(p).value == "BUY")
    assert sym_buy >= asym_buy
