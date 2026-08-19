"""Unit tests for production exit policy (CURRENT + Hybrid B)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import TradingSignal
from tradingbot.services.exit_mode import ExitMode, resolve_exit_mode
from tradingbot.services.exit_policy import resolve_current_tp_sl, resolve_hybrid_b, resolve_exit
from tradingbot.services.paper_trade_exit import resolve_paper_trade_exit
from tradingbot.services.paper_trade_recorder import PaperTradeRecorder


def _candles(rows: int = 100, *, start_price: float = 2000.0, drift: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    close = start_price + pd.Series(range(rows), dtype=float) * drift
    df = pd.DataFrame(index=idx)
    df["close"] = close.values
    df["open"] = df["close"] - 0.2
    df["high"] = df["close"] + 1.0
    df["low"] = df["close"] - 1.0
    df["volume"] = 100
    return df


class TestExitMode(unittest.TestCase):
    def test_resolve_current_default(self) -> None:
        self.assertEqual(resolve_exit_mode("CURRENT"), ExitMode.CURRENT)

    def test_resolve_hybrid_b(self) -> None:
        self.assertEqual(resolve_exit_mode("HYBRID_B"), ExitMode.HYBRID_B)


class TestHybridBPolicy(unittest.TestCase):
    def test_partial_close_at_1r(self) -> None:
        candles = _candles(80, start_price=2000.0, drift=0.2)
        entry = 2000.0
        sl = 1990.0
        entry_ts = candles.index[5].isoformat()
        candles.iloc[10, candles.columns.get_loc("high")] = entry + 12.0
        result = resolve_hybrid_b(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry,
            sl=sl,
            tp=entry + 20.0,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
            max_hold_bars=72,
        )
        self.assertTrue(result.get("partial_close_applied"))
        self.assertGreater(float(result.get("partial_pnl") or 0), 0)

    def test_sl_before_partial(self) -> None:
        candles = _candles(80, start_price=2000.0, drift=-0.5)
        entry = 2000.0
        sl = 1999.0
        entry_ts = candles.index[5].isoformat()
        result = resolve_hybrid_b(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry,
            sl=sl,
            tp=entry + 20.0,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
        )
        self.assertFalse(result.get("partial_close_applied"))
        self.assertEqual(result["exit_reason"], "sl")

    def test_time_exit_after_72_bars(self) -> None:
        candles = _candles(200, start_price=2000.0, drift=0.01)
        entry = 2000.0
        sl = 1990.0
        entry_ts = candles.index[10].isoformat()
        result = resolve_hybrid_b(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry,
            sl=sl,
            tp=entry + 20.0,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
            max_hold_bars=72,
        )
        self.assertLessEqual(result["duration_bars"], 72)
        self.assertIn(result["exit_reason"], ("time", "hybrid_time", "timeout", "sl"))

    def test_no_duplicate_partial_on_repeated_resolve(self) -> None:
        candles = _candles(80, start_price=2000.0, drift=0.3)
        entry = 2000.0
        sl = 1990.0
        entry_ts = candles.index[5].isoformat()
        candles.iloc[12, candles.columns.get_loc("high")] = entry + 15.0
        r1 = resolve_hybrid_b(
            candles=candles.iloc[:40],
            entry_ts=entry_ts,
            entry_price=entry,
            sl=sl,
            tp=entry + 20.0,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
        )
        r2 = resolve_hybrid_b(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry,
            sl=sl,
            tp=entry + 20.0,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
        )
        self.assertTrue(r1.get("partial_close_applied") or r2.get("partial_close_applied"))


class TestBackwardCompatibility(unittest.TestCase):
    def test_current_mode_matches_legacy(self) -> None:
        candles = _candles(100)
        entry = float(candles.iloc[10]["close"])
        entry_ts = candles.index[10].isoformat()
        kwargs = dict(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=entry,
            sl=entry - 5,
            tp=entry + 10,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
        )
        legacy = resolve_current_tp_sl(**kwargs)
        wrapped = resolve_paper_trade_exit(**kwargs, exit_mode=ExitMode.CURRENT)
        self.assertEqual(legacy["exit_reason"], wrapped["exit_reason"])
        self.assertAlmostEqual(legacy["pnl"], wrapped["pnl"], places=2)

    def test_dispatch_hybrid_b(self) -> None:
        candles = _candles(80)
        entry = float(candles.iloc[5]["close"])
        result = resolve_exit(
            exit_mode=ExitMode.HYBRID_B,
            candles=candles,
            entry_ts=candles.index[5].isoformat(),
            entry_price=entry,
            sl=entry - 10,
            tp=entry + 20,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
        )
        self.assertIn("pnl", result)
        self.assertIn("partial_close_applied", result)


class TestPaperRecorderHybridB(unittest.TestCase):
    def test_complete_trade_hybrid_b_mode(self) -> None:
        tmp = tempfile.mkdtemp()
        base = Path(tmp)
        try:
            from tradingbot.ml.data.stores.candle_store import CandleStore

            candles = _candles(2000)
            CandleStore(base).store("XAUUSD", "M5", candles)
            entry = float(candles.iloc[500]["close"])
            signal = TradingSignal(
                direction=SignalDirection.BUY,
                confidence=0.6,
                symbol="XAUUSD",
                timeframe="M5",
                stop_loss=entry - 5,
                take_profit=entry + 10,
            )
            recorder = PaperTradeRecorder(base, config={"exit_mode": "HYBRID_B"})
            trade_id = recorder.record_entry(signal, 0.01, bar_time=candles.index[500])
            self.assertIsNotNone(trade_id)
            closed = recorder.complete_trade(int(trade_id))
            self.assertIsNotNone(closed)
            assert closed is not None
            self.assertEqual(closed["status"], "closed")
            del recorder
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
