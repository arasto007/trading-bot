"""Phase 1A PA unit tests — BOS, FVG, sweep, quality, SL/TP, dedup."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from tradingbot.domain.pa_hardening import (
    clear_pa_dedup_cache,
    compute_quality_score,
    confirm_fvg_fill,
    detect_bos_continuation,
    detect_liquidity_sweep_flag,
    is_duplicate_pa_signal,
    session_range_breakout_stats,
)
from tradingbot.domain.gold_strategies import evaluate_gold_setup
from tradingbot.domain.price_action import (
    FairValueGap,
    PriceActionSetup,
    SetupType,
    StructureBreak,
    enrich_price_action,
)


def _ohlcv(n: int = 120, *, spike_at: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    close = 2000 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.2, 1.5, n)
    low = close - rng.uniform(0.2, 1.5, n)
    open_ = close + rng.uniform(-0.3, 0.3, n)
    if spike_at is not None:
        high[spike_at] += 8.0
        low[spike_at] -= 8.0
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
    return df


def _cfg() -> dict:
    return {
        "GOLD_STRATEGY_MODE": "london_sweep",
        "MIN_CONFLUENCE": 2.0,
        "MIN_RR": 1.5,
        "SL_ATR_MULT": 0.35,
        "MIN_CONFIDENCE": 0.45,
        "SWEEP_LOOKBACK_BARS": 12,
        "MIN_RANGE_ATR": 0.2,
        "MIN_QUALITY_SCORE": 0,
        "USE_REGIME_FILTER": False,
    }


class TestBOSDetection:
    def test_bos_continuation_true(self):
        breaks = [StructureBreak(100, 2005.0, "bos", 1)]
        assert detect_bos_continuation(breaks, 105, 1) is True

    def test_bos_continuation_false_wrong_direction(self):
        breaks = [StructureBreak(100, 2005.0, "bos", 1)]
        assert detect_bos_continuation(breaks, 105, -1) is False


class TestFVGDetection:
    def test_fvg_fill_confirmed(self):
        gap = FairValueGap(90, 2002.0, 2000.0, 1)
        assert confirm_fvg_fill([gap], price=2001.0, direction=1, i=95) is True

    def test_fvg_fill_not_in_zone(self):
        gap = FairValueGap(90, 2002.0, 2000.0, 1)
        assert confirm_fvg_fill([gap], price=1990.0, direction=1, i=95) is False


class TestSweepDetection:
    def test_sweep_on_enriched_data(self):
        df = _ohlcv(150)
        cfg = _cfg()
        df = enrich_price_action(df, cfg, at_index=len(df) - 1)
        i = len(df) - 1
        swings = df.attrs.get("pa_swings", [])
        assert isinstance(detect_liquidity_sweep_flag(df, swings, i), bool)


class TestQualityScore:
    def test_quality_score_bounds(self):
        setup = PriceActionSetup(
            direction=1,
            setup=SetupType.LIQUIDITY_SWEEP,
            entry=2000.0,
            stop_loss=1995.0,
            take_profit=2010.0,
            confidence=0.7,
            confluence=3.0,
            metadata={},
        )
        score = compute_quality_score(
            setup=setup,
            bos_confirmed=True,
            fvg_confirmed=True,
            liquidity_sweep=True,
            session_breakout=True,
            confluence=3.0,
        )
        assert 0 <= score <= 100

    def test_quality_score_minimum(self):
        setup = PriceActionSetup(
            direction=1,
            setup=SetupType.FVG_FILL,
            entry=2000.0,
            stop_loss=1995.0,
            take_profit=2010.0,
            confidence=0.5,
            confluence=0.5,
            metadata={},
        )
        score = compute_quality_score(
            setup=setup,
            bos_confirmed=False,
            fvg_confirmed=False,
            liquidity_sweep=False,
            session_breakout=False,
            confluence=0.5,
        )
        assert score >= 0


class TestSLTPGeneration:
    def test_evaluate_gold_setup_sl_tp(self):
        df = _ohlcv(200)
        cfg = _cfg()
        df = enrich_price_action(df, cfg, at_index=len(df) - 1)
        setup = evaluate_gold_setup(df, len(df) - 1, cfg, timeframe="M5")
        if setup is not None:
            assert setup.stop_loss != setup.entry
            assert setup.take_profit != setup.entry
            risk = abs(setup.entry - setup.stop_loss)
            reward = abs(setup.take_profit - setup.entry)
            assert reward / risk >= cfg["MIN_RR"] - 0.01


class TestDuplicatePrevention:
    def test_duplicate_signal_blocked(self):
        clear_pa_dedup_cache()
        ts = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
        assert is_duplicate_pa_signal("XAUUSD", 1, ts, cooldown_minutes=10) is False
        assert is_duplicate_pa_signal("XAUUSD", 1, ts, cooldown_minutes=10) is True


class TestSessionRangeStats:
    def test_session_range_stats_keys(self):
        df = _ohlcv(80)
        df["atr"] = 2.0
        stats = session_range_breakout_stats(df, 60, _cfg())
        assert "range_high" in stats
        assert "breakout" in stats
