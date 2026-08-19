"""Simulated trade execution — open, close, TP/SL resolution."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradingbot.ml.dataset.labels import compute_atr_at, compute_sl_tp, label_from_future_candles
from tradingbot.ml.dataset.schema import DEFAULT_RR_SL, DEFAULT_RR_TP
from tradingbot.ml.paper._types import PaperConfig, PaperTrade, SignalMode, TradeStatus, new_trade_id


@dataclass
class TradeExecutor:
    """Open and close simulated trades with fixed TP=2R / SL=1R."""

    config: PaperConfig | None = None

    def __post_init__(self) -> None:
        self.config = self.config or PaperConfig()

    def open_trade(
        self,
        *,
        timestamp: str,
        symbol: str,
        direction: int,
        entry_price: float,
        signal_source: str,
        session: str,
        slippage: float = 0.0,
        spread_cost: float = 0.0,
        risk_unit: float | None = None,
    ) -> PaperTrade:
        risk = risk_unit if risk_unit is not None else entry_price * 0.001
        sl, tp = compute_sl_tp(
            entry_price,
            direction,
            risk,
            tp_r=self.config.tp_r,
            sl_r=self.config.sl_r,
        )
        return PaperTrade(
            trade_id=new_trade_id(),
            timestamp=timestamp,
            symbol=symbol,
            direction=direction,
            signal_source=signal_source,
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            risk_unit=risk,
            slippage=slippage,
            spread_cost=spread_cost,
            session=session,
        )

    def resolve_trade_on_candles(
        self,
        trade: PaperTrade,
        candles: pd.DataFrame,
        entry_index: int,
    ) -> PaperTrade:
        """Resolve TP/SL using only candles after entry (no lookahead at entry)."""
        result = label_from_future_candles(
            candles,
            entry_index,
            trade.direction,
            future_window_bars=self.config.future_window_bars,
            atr_period=self.config.atr_period,
            tp_r=self.config.tp_r,
            sl_r=self.config.sl_r,
            entry_price=trade.entry_price,
        )
        trade.exit_price = result.take_profit if result.tp_hit else result.stop_loss if result.sl_hit else trade.entry_price
        trade.bars_held = result.resolution_bar - entry_index if result.resolution_bar else 0
        if result.tp_hit:
            trade.r_multiple = self.config.tp_r
            trade.exit_reason = "TP"
        elif result.sl_hit:
            trade.r_multiple = -self.config.sl_r
            trade.exit_reason = "SL"
        else:
            trade.r_multiple = 0.0
            trade.exit_reason = "UNRESOLVED"
        trade.status = TradeStatus.CLOSED.value
        return trade

    @staticmethod
    def resolve_signal(record, mode: SignalMode) -> tuple[str, int]:
        """Map decision record fields to signal string and direction."""
        from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL, DECISION_WAIT
        from tradingbot.ml.memory.schema import direction_from_decision

        if mode == SignalMode.RULE:
            sig = str(record.rule_signal).upper()
        elif mode == SignalMode.ML:
            sig = DECISION_BUY if record.ml_prediction == 1 and record.ml_probability >= 0.5 else DECISION_WAIT
            if record.direction < 0 and record.ml_prediction == 1:
                sig = DECISION_SELL
        elif mode == SignalMode.AB:
            sig = str(record.hybrid_decision).upper()
            if record.rule_signal.upper() in (DECISION_BUY, DECISION_SELL) and sig == DECISION_WAIT:
                sig = record.rule_signal.upper()
        else:
            sig = str(record.hybrid_decision).upper()

        if sig not in (DECISION_BUY, DECISION_SELL):
            return DECISION_WAIT, 0
        if mode == SignalMode.HYBRID and record.ml_prediction != 1:
            return DECISION_WAIT, 0
        if mode == SignalMode.HYBRID and record.final_score < 0.60:
            return DECISION_WAIT, 0
        direction = direction_from_decision(sig, fallback=record.direction)
        return sig, direction
