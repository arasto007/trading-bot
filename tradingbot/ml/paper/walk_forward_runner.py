"""Walk-forward paper trading simulation windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.memory.schema import DecisionRecord
from tradingbot.ml.paper._types import PaperConfig, SignalMode
from tradingbot.ml.paper.engine import PaperTradingEngine


DEFAULT_WINDOWS = (1000, 5000)


@dataclass
class WalkForwardResult:
    window_size: int
    start_index: int
    end_index: int
    equity_curve: list[float]
    metrics: dict[str, Any]
    trades: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_size": self.window_size,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "equity_curve": self.equity_curve,
            "metrics": self.metrics,
            "trades": self.trades,
        }


@dataclass
class WalkForwardRunner:
    """Run sequential paper trading in chronological windows."""

    window_sizes: tuple[int, ...] = DEFAULT_WINDOWS
    config: PaperConfig | None = None

    def run(
        self,
        candles: pd.DataFrame,
        decisions: list[DecisionRecord],
        *,
        signal_mode: SignalMode = SignalMode.HYBRID,
    ) -> list[WalkForwardResult]:
        results: list[WalkForwardResult] = []
        n = len(candles)
        for window in self.window_sizes:
            if n < window:
                subset_candles = candles.copy()
                subset_decisions = decisions
                start, end = 0, n
            else:
                start = n - window
                end = n
                subset_candles = candles.iloc[start:end].reset_index(drop=True)
                ts_min = self._ts(subset_candles, 0)
                ts_max = self._ts(subset_candles, len(subset_candles) - 1)
                subset_decisions = [
                    d for d in decisions
                    if ts_min <= d.timestamp <= ts_max
                ] if ts_min and ts_max else decisions

            engine = PaperTradingEngine(config=self.config, signal_mode=signal_mode)
            sim = engine.run(subset_candles, subset_decisions, bar_offset=start)
            results.append(
                WalkForwardResult(
                    window_size=window,
                    start_index=start,
                    end_index=end,
                    equity_curve=sim["equity_curve"],
                    metrics=sim["metrics"],
                    trades=sim["metrics"].get("trade_frequency", 0),
                )
            )
        return results

    @staticmethod
    def _ts(candles: pd.DataFrame, idx: int) -> str:
        if "timestamp" in candles.columns:
            return str(pd.to_datetime(candles["timestamp"].iloc[idx], utc=True))
        if isinstance(candles.index, pd.DatetimeIndex):
            return str(candles.index[idx])
        return ""
