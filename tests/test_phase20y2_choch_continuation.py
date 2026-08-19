"""Phase 20Y-2 ? CHoCH continuation detector and quality scoring."""
from __future__ import annotations

import pandas as pd

from tradingbot.domain.pa_hardening import (
    compute_quality_score,
    detect_choch_continuation,
)
from tradingbot.domain.price_action import PriceActionSetup, SetupType, StructureBreak


def _df(*, close_choch: float = 102.0, open_choch: float = 100.0, last_close: float = 102.5):
    n = 20
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    close = [100.0] * n
    close[15] = close_choch
    close[19] = last_close
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": close,
            "atr": [1.0] * n,
        },
        index=idx,
    )
    df.iloc[15, df.columns.get_loc("open")] = open_choch
    df.iloc[15, df.columns.get_loc("close")] = close_choch
    return df


def test_buy_choch_continuation_true():
    df = _df()
    df.attrs["pa_breaks"] = [StructureBreak(15, 101.0, "choch", 1)]
    assert detect_choch_continuation(df, 1, lookback=8, at_index=19, reclaim_index=12) is True


def test_sell_choch_continuation_true():
    df = _df(close_choch=97.0, open_choch=100.0, last_close=96.5)
    df.attrs["pa_breaks"] = [StructureBreak(15, 99.0, "choch", -1)]
    assert detect_choch_continuation(df, -1, lookback=8, at_index=19, reclaim_index=12) is True


def test_last_break_must_be_choch_not_bos():
    df = _df()
    df.attrs["pa_breaks"] = [StructureBreak(15, 101.0, "bos", 1)]
    assert detect_choch_continuation(df, 1, lookback=8, at_index=19, reclaim_index=12) is False


def test_wrong_direction_rejected():
    df = _df()
    df.attrs["pa_breaks"] = [StructureBreak(15, 101.0, "choch", -1)]
    assert detect_choch_continuation(df, 1, lookback=8, at_index=19, reclaim_index=12) is False


def test_displacement_below_atr_rejected():
    df = _df(close_choch=100.5, open_choch=100.0, last_close=102.5)
    df.attrs["pa_breaks"] = [StructureBreak(15, 101.0, "choch", 1)]
    assert detect_choch_continuation(df, 1, lookback=8, at_index=19, reclaim_index=12) is False


def test_reclaim_distance_over_lookback_rejected():
    df = _df()
    df.attrs["pa_breaks"] = [StructureBreak(15, 101.0, "choch", 1)]
    assert detect_choch_continuation(df, 1, lookback=8, at_index=19, reclaim_index=10) is False


def _setup():
    return PriceActionSetup(
        direction=1,
        setup=SetupType.LIQUIDITY_SWEEP,
        entry=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        confidence=0.7,
        confluence=3.2,
        metadata={},
    )


def test_quality_bos_plus_12_not_stacked_with_choch():
    base = compute_quality_score(
        setup=_setup(),
        bos_confirmed=False,
        fvg_confirmed=False,
        liquidity_sweep=True,
        session_breakout=False,
        confluence=3.2,
        choch_confirmed=False,
    )
    bos = compute_quality_score(
        setup=_setup(),
        bos_confirmed=True,
        fvg_confirmed=False,
        liquidity_sweep=True,
        session_breakout=False,
        confluence=3.2,
        choch_confirmed=True,
    )
    choch = compute_quality_score(
        setup=_setup(),
        bos_confirmed=False,
        fvg_confirmed=False,
        liquidity_sweep=True,
        session_breakout=False,
        confluence=3.2,
        choch_confirmed=True,
    )
    assert bos - base == 12
    assert choch - base == 8
    assert bos - choch == 4
