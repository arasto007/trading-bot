"""Outcome evaluation using future candles — reuses dataset labeling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.labels import label_from_future_candles
from tradingbot.ml.dataset.schema import DEFAULT_FUTURE_WINDOW_M5, DEFAULT_RR_SL, DEFAULT_RR_TP
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord, direction_from_decision, utc_now_iso


@dataclass
class OutcomeEvaluator:
    """Evaluate shadow decisions against future market candles (offline)."""

    future_window_bars: int = DEFAULT_FUTURE_WINDOW_M5
    tp_r: float = DEFAULT_RR_TP
    sl_r: float = DEFAULT_RR_SL
    atr_period: int = 14

    def evaluate(
        self,
        record: DecisionRecord,
        candles: pd.DataFrame,
        *,
        entry_index: int | None = None,
    ) -> OutcomeRecord:
        idx = entry_index if entry_index is not None else self._find_entry_index(candles, record.timestamp)
        direction = record.direction or direction_from_decision(record.hybrid_decision)
        if direction == 0:
            direction = direction_from_decision(record.rule_signal, fallback=1)

        entry_price = record.entry_price or None
        if entry_price == 0.0:
            entry_price = None

        result = label_from_future_candles(
            candles,
            idx,
            direction,
            future_window_bars=self.future_window_bars,
            atr_period=self.atr_period,
            tp_r=self.tp_r,
            sl_r=self.sl_r,
            entry_price=entry_price,
        )

        r_multiple = self._r_multiple(result)
        return OutcomeRecord(
            decision_id=record.decision_id,
            evaluated_at=utc_now_iso(),
            future_return=result.future_return,
            tp_hit=result.tp_hit,
            sl_hit=result.sl_hit,
            max_favorable_excursion=result.mfe,
            max_adverse_excursion=result.mae,
            r_multiple=r_multiple,
            label=int(result.label),
        )

    @staticmethod
    def _r_multiple(result: Any) -> float:
        if result.tp_hit:
            return float(DEFAULT_RR_TP)
        if result.sl_hit:
            return -float(DEFAULT_RR_SL)
        return 0.0

    def _find_entry_index(self, candles: pd.DataFrame, timestamp: str) -> int:
        if candles is None or candles.empty:
            return 0
        target = pd.to_datetime(timestamp, utc=True)
        if "timestamp" in candles.columns:
            ts = pd.to_datetime(candles["timestamp"], utc=True)
            pos = int(ts.searchsorted(target, side="right") - 1)
            return max(0, min(pos, len(candles) - 1))
        if isinstance(candles.index, pd.DatetimeIndex):
            idx = candles.index.searchsorted(target, side="right") - 1
            return max(0, min(int(idx), len(candles) - 1))
        return max(0, len(candles) - self.future_window_bars - 2)
