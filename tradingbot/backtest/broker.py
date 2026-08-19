"""
بروکر شبیه‌سازی‌شده — پیاده‌سازی IOrderExecutor برای بک‌تست.

مسئول: باز کردن پوزیشن مجازی، بستن جزئی/کامل، چک SL/TP درون‌کندلی،
هزینه‌ها (spread/slippage/commission)، و دنبال‌کردن balance/equity.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.models import ClosedTrade, VirtualPosition
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import ExecutionResult, TradingSignal
from tradingbot.domain.position_logic import pip_size
from tradingbot.domain.session_logic import variable_slippage_pips, variable_spread_pips

logger = logging.getLogger(__name__)


class SimulatedBroker:
    """IOrderExecutor شبیه‌سازی‌شده + موتور حساب‌داری معاملات."""

    def __init__(self, config: BacktestConfig, data_source) -> None:
        self._cfg = config
        self._data = data_source
        self.balance = config.initial_balance
        self.equity = config.initial_balance
        self.open_positions: list[VirtualPosition] = []
        self.closed_trades: list[ClosedTrade] = []
        self._next_ticket = 1
        self._last_day: str = ""
        self._day_start_balance: float = config.initial_balance

    # ----------------------------------------------------- IOrderExecutor
    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        symbol = signal.symbol
        bar = self._data.current_bar(symbol)
        if bar is None:
            return ExecutionResult(success=False, message="no current bar")

        is_buy = signal.direction == SignalDirection.BUY
        pip = pip_size(symbol)
        close = float(bar["close"])
        hour = self._current_hour()
        spread_pips = (
            variable_spread_pips(self._cfg.spread_pips, hour)
            if self._cfg.variable_spread
            else self._cfg.spread_pips
        )
        slip_pips = (
            variable_slippage_pips(self._cfg.slippage_pips, hour)
            if self._cfg.variable_spread
            else self._cfg.slippage_pips
        )
        half_spread = (spread_pips / 2.0) * pip
        slip = slip_pips * pip
        # خرید گران‌تر، فروش ارزان‌تر (به ضرر ما)
        entry = close + half_spread + slip if is_buy else close - half_spread - slip

        lot = self._round_lot(lot)
        commission = self._cfg.commission_per_lot * lot

        sl = signal.stop_loss or 0.0
        tp = signal.take_profit or 0.0
        initial_risk = abs(entry - sl) if sl > 0 else 0.0

        meta = signal.metadata or {}
        entry_features = dict(meta.get("_entry_features") or {})
        if not entry_features:
            from tradingbot.domain.trade_features import capture_entry_features, estimate_spread_pips

            entry_features = capture_entry_features(
                signal,
                {"ohlcv": None, "htf_bias": meta.get("htf_bias", 0), "current_time": self._data.current_time()},
                str(meta.get("_regime", "RANGING")),
                spread_pips=spread_pips,
                entry_price=entry,
            )

        pos = VirtualPosition(
            ticket=self._next_ticket,
            symbol=symbol,
            is_buy=is_buy,
            entry_price=entry,
            volume=lot,
            sl=sl,
            tp=tp,
            entry_index=self._data.cursor,
            entry_time=self._data.current_time(),
            strategy=signal.strategy_name,
            initial_risk=initial_risk,
            original_volume=lot,
            partial_hits=[],
            commission_paid=commission,
            entry_features=entry_features,
            entry_sl=float(sl),
        )
        self._next_ticket += 1
        self.balance -= commission
        self.open_positions.append(pos)
        logger.debug(
            "OPEN #%d %s %s lot=%.2f @ %.5f sl=%.5f tp=%.5f",
            pos.ticket, symbol, "BUY" if is_buy else "SELL", lot, entry, sl, tp,
        )
        return ExecutionResult(success=True, ticket=pos.ticket, message="sim open")

    def manage_open_positions(self, market_key: str) -> None:
        # مدیریت در موتور بک‌تست به‌صورت صریح انجام می‌شود.
        return None

    # ----------------------------------------------------- bar processing
    def positions_for(self, symbol: str) -> list[VirtualPosition]:
        return [p for p in self.open_positions if p.symbol == symbol]

    def check_exits(self, symbol: str, bar, allow_same_bar: bool = False) -> None:
        """چک SL/TP درون‌کندلی با high/low. SL در صورت برخورد همزمان مقدم است."""
        high = float(bar["high"])
        low = float(bar["low"])
        pip = pip_size(symbol)
        hour = self._current_hour()
        slip_pips = (
            variable_slippage_pips(self._cfg.slippage_pips, hour)
            if self._cfg.variable_spread
            else self._cfg.slippage_pips
        )
        slip = slip_pips * pip
        for pos in self.positions_for(symbol):
            if not allow_same_bar and pos.entry_index == self._data.cursor:
                continue
            if pos.is_buy:
                if pos.sl > 0 and low <= pos.sl:
                    self.close_position(pos, pos.sl - slip, "sl")
                elif pos.tp > 0 and high >= pos.tp:
                    self.close_position(pos, pos.tp - slip, "tp")
            else:
                if pos.sl > 0 and high >= pos.sl:
                    self.close_position(pos, pos.sl + slip, "sl")
                elif pos.tp > 0 and low <= pos.tp:
                    self.close_position(pos, pos.tp + slip, "tp")

    def partial_close(self, pos: VirtualPosition, volume: float, price: float, reason: str) -> None:
        volume = min(volume, pos.volume)
        if volume <= 0:
            return
        pnl = pos.pnl_for_volume(price, volume)
        pos.realized_pnl += pnl
        self.balance += pnl
        pos.volume = round(pos.volume - volume, 2)
        logger.debug("PARTIAL #%d %s vol=%.2f @ %.5f pnl=%.2f", pos.ticket, reason, volume, price, pnl)
        if pos.volume <= 0:
            self._finalize(pos, price, reason)

    def close_position(self, pos: VirtualPosition, price: float, reason: str) -> None:
        pnl = pos.pnl_for_volume(price, pos.volume)
        pos.realized_pnl += pnl
        self.balance += pnl
        pos.volume = 0.0
        self._finalize(pos, price, reason)

    def _finalize(self, pos: VirtualPosition, price: float, reason: str) -> None:
        if pos in self.open_positions:
            self.open_positions.remove(pos)
        from tradingbot.domain.trade_features import r_multiple

        r_mult = r_multiple(
            pos.realized_pnl - pos.commission_paid,
            pos.entry_price,
            pos.entry_sl or pos.sl,
            pos.original_volume,
            pos.symbol,
            pos.is_buy,
        )
        self.closed_trades.append(
            ClosedTrade(
                symbol=pos.symbol,
                is_buy=pos.is_buy,
                entry_price=pos.entry_price,
                exit_price=price,
                volume=pos.original_volume,
                entry_time=pos.entry_time,
                exit_time=self._data.current_time(),
                pnl=pos.realized_pnl - pos.commission_paid,
                reason=reason,
                strategy=pos.strategy,
                exit_index=self._data.cursor,
                entry_sl=pos.entry_sl or pos.sl,
                initial_risk=pos.initial_risk,
                entry_features=dict(pos.entry_features),
                r_multiple=round(r_mult, 4),
            )
        )
        logger.debug("CLOSE #%d %s @ %.5f net=%.2f", pos.ticket, reason, price, pos.realized_pnl)

    def mark_equity(self) -> None:
        unrealized = 0.0
        for pos in self.open_positions:
            bar = self._data.current_bar(pos.symbol)
            if bar is not None:
                unrealized += pos.unrealized_pnl(float(bar["close"]))
        self.equity = self.balance + unrealized

    def close_all(self, reason: str = "end") -> None:
        for pos in list(self.open_positions):
            bar = self._data.current_bar(pos.symbol)
            price = float(bar["close"]) if bar is not None else pos.entry_price
            self.close_position(pos, price, reason)

    def snapshot(self) -> dict[str, Any]:
        current_time = self._data.current_time()
        day = str(current_time)[:10] if current_time is not None else ""
        if day and day != self._last_day:
            self._last_day = day
            self._day_start_balance = self.balance
        daily_pnl = 0.0
        trades_today = 0
        last_exit_bar = None
        for t in self.closed_trades:
            exit_day = str(t.exit_time)[:10] if t.exit_time else ""
            if exit_day == day:
                daily_pnl += t.pnl
                trades_today += 1
        if self.closed_trades:
            last_exit_bar = self.closed_trades[-1].exit_index
        return {
            "balance": self.balance,
            "equity": self.equity,
            "cursor": self._data.cursor,
            "current_day": day,
            "day_start_balance": self._day_start_balance,
            "current_time": current_time,
            "daily_pnl": daily_pnl,
            "trades_today": trades_today,
            "last_exit_bar": last_exit_bar,
            "open_positions": [
                {"symbol": p.symbol, "is_buy": p.is_buy, "volume": p.volume}
                for p in self.open_positions
            ],
        }

    def _round_lot(self, lot: float) -> float:
        step = self._cfg.lot_step
        lot = max(self._cfg.min_lot, min(lot, self._cfg.max_lot))
        return round(round(lot / step) * step, 2)

    def _current_hour(self) -> int:
        ts = self._data.current_time()
        if ts is None:
            return 12
        if hasattr(ts, "hour"):
            return int(ts.hour)
        return 12
