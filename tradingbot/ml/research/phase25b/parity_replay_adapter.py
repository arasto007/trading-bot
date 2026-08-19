"""Synthetic forming-bar replay adapter for offline parity with live paper pipeline."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from tradingbot.domain.models import MarketKey
from tradingbot.ml.integration.replay_market_data import ReplayMarketDataAdapter


def timeframe_delta(timeframe: str) -> timedelta:
    tf = str(timeframe).upper()
    if tf.startswith("M") and tf[1:].isdigit():
        return timedelta(minutes=int(tf[1:]))
    if tf.startswith("H") and tf[1:].isdigit():
        return timedelta(hours=int(tf[1:]))
    if tf == "D1":
        return timedelta(days=1)
    return timedelta(minutes=5)


class ParityReplayMarketDataAdapter(ReplayMarketDataAdapter):
    """
    Replay adapter that appends a synthetic forming bar to each OHLCV slice.

    Live MT5 always includes one in-progress candle; ``exclude_forming_bar`` drops it.
    Frozen CandleStore history is all closed — without a synthetic forming bar, replay
    decisions shift one bar earlier than production paper trading.
    """

    def __init__(self, candles: pd.DataFrame, *, timeframe: str = "M5") -> None:
        super().__init__(candles)
        self._tf_delta = timeframe_delta(timeframe)

    def get_ohlcv(self, market: MarketKey, bars: int = 500) -> pd.DataFrame | None:
        df = super().get_ohlcv(market, bars=bars)
        if df is None or df.empty:
            return df
        return self._append_forming_bar(df)

    def _append_forming_bar(self, df: pd.DataFrame) -> pd.DataFrame:
        last = df.iloc[-1]
        next_ts = pd.to_datetime(df.index[-1], utc=True) + self._tf_delta
        forming = pd.DataFrame(
            {
                "open": [float(last["open"])],
                "high": [float(last["high"])],
                "low": [float(last["low"])],
                "close": [float(last["close"])],
                "volume": [float(last.get("volume", 0.0))],
            },
            index=pd.DatetimeIndex([next_ts], tz="UTC"),
        )
        return pd.concat([df, forming])
