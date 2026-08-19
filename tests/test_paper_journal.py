"""Unit tests for paper journal infrastructure."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import TradingSignal
from tradingbot.services.paper_fill_resolver import resolve_paper_fill
from tradingbot.services.paper_trade_recorder import PaperTradeRecorder
from tradingbot.services.trade_journal import TradeJournal


def _write_candles(base: Path, symbol: str = "XAUUSD", timeframe: str = "M5", rows: int = 2000) -> None:
    from tradingbot.ml.data.stores.candle_store import CandleStore

    idx = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    close = 2000.0 + pd.Series(range(rows), dtype=float)
    df = pd.DataFrame(index=idx)
    df["close"] = close.values
    df["open"] = df["close"] - 0.5
    df["high"] = df["close"] + 1.0
    df["low"] = df["close"] - 1.0
    df["volume"] = 100
    CandleStore(base).store(symbol, timeframe, df)


class TestPaperFillResolver(unittest.TestCase):
    def test_candle_fallback_when_mt5_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_candles(base)
            signal = TradingSignal(
                direction=SignalDirection.BUY,
                confidence=0.6,
                symbol="XAUUSD",
                timeframe="M5",
                stop_loss=1990.0,
                take_profit=2010.0,
            )
            fill, spread, source = resolve_paper_fill(signal, base_dir=base, mt5_price=None)
            self.assertGreater(fill, 0)
            self.assertIn(source, ("candle_close", "sl_tp_midpoint", "mt5_tick"))
            self.assertGreater(spread, 0)


class TestPaperTradeRecorder(unittest.TestCase):
    def test_entry_and_completion_persist_all_fields(self) -> None:
        tmp = tempfile.mkdtemp()
        base = Path(tmp)
        try:
            _write_candles(base)
            from tradingbot.ml.data.stores.candle_store import CandleStore

            candles = CandleStore(base).load("XAUUSD", "M5")
            self.assertIsNotNone(candles)
            assert candles is not None
            if not isinstance(candles.index, pd.DatetimeIndex):
                candles = candles.set_index("time")
            candles.index = pd.DatetimeIndex(pd.to_datetime(candles.index, utc=True))

            bar_time = candles.index[500]
            entry = float(candles.iloc[500]["close"])
            signal = TradingSignal(
                direction=SignalDirection.BUY,
                confidence=0.62,
                symbol="XAUUSD",
                timeframe="M5",
                stop_loss=entry - 5,
                take_profit=entry + 10,
                metadata={
                    "regime": "TREND",
                    "engine_name": "trend_rf_v41",
                    "risk_percent": 0.5,
                    "unified_checksum": "abc123",
                    "trace_id": "trace001",
                },
            )
            recorder = PaperTradeRecorder(base)
            trade_id = recorder.record_entry(signal, 0.01, mt5_price=None, bar_time=bar_time)
            self.assertIsNotNone(trade_id)
            result = recorder.complete_trade(int(trade_id), candles=candles)
            self.assertIsNotNone(result)

            journal = TradeJournal(base)
            rows = journal.list_completed_paper_trades()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertGreater(row["fill_price"], 0)
            self.assertGreater(row["exit_price"], 0)
            self.assertIsNotNone(row["time_close"])
            self.assertEqual(row["status"], "closed")
        finally:
            import gc
            import shutil

            gc.collect()
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
