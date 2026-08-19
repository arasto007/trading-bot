"""
آداپتر اجرای سفارش MT5 — dry-run / paper / live + ثبت slippage.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.mt5_utils import ensure_mt5_connected
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.domain import order_logic
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import ExecutionResult, TradingSignal
from tradingbot.domain.position_logic import pip_size
from tradingbot.infra.logging import get_logger
from tradingbot.ports.execution import IOrderExecutor
from tradingbot.services.execution_mode import is_dry_run, is_paper, mode_label
from tradingbot.services.rejection_events import log_rejection_event
from tradingbot.services.trade_journal import TradeJournal

logger = logging.getLogger(__name__)

_MAGIC = 234000
_DEVIATION = 20


class Mt5ExecutionAdapter(IOrderExecutor):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or load_legacy_config()
        base_dir = self._config.get("BASE_DIR", ".")
        self._logger = get_logger("mt5_execution", base_dir)
        self._broker_symbols: dict[str, str] = {}
        self._journal = TradeJournal(base_dir)

    def _broker_symbol(self, symbol: str) -> str:
        if symbol not in self._broker_symbols:
            self._broker_symbols[symbol] = resolve_broker_symbol(symbol, self._config)
        return self._broker_symbols[symbol]

    def execute(self, signal: TradingSignal, lot: float) -> ExecutionResult:
        mode = mode_label()
        if is_dry_run():
            logger.info(
                "DRY_RUN: skip order %s %s lot=%s",
                signal.symbol,
                signal.direction.name,
                lot,
            )
            self._journal.log_execution(
                mode=mode,
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                direction=signal.direction.name,
                lot=lot,
                requested_price=0.0,
                fill_price=None,
                slippage_pips=None,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                ticket=None,
                success=True,
                message="dry_run",
            )
            return ExecutionResult(success=True, message="dry_run — order not sent")

        if is_paper():
            from tradingbot.services.paper_trade_recorder import PaperTradeRecorder

            mt5_price = self._quote_price(signal)
            recorder = PaperTradeRecorder(
                self._config.get("BASE_DIR", "."),
                config=self._config,
            )
            trade_id = recorder.record_entry(signal, lot, mt5_price=mt5_price or None)
            if trade_id is None:
                return ExecutionResult(success=False, message="paper — fill price unresolved")
            logger.info(
                "PAPER: simulated %s %s lot=%s journal_id=%s",
                signal.symbol,
                signal.direction.name,
                lot,
                trade_id,
            )
            return ExecutionResult(success=True, message="paper — simulated fill", ticket=-trade_id)

        if not ensure_mt5_connected(
            self._config, symbols=[signal.symbol], attach_only=True, strict_account=True
        ):
            return ExecutionResult(success=False, message="MT5 not connected")

        canonical = signal.symbol.upper()
        broker_symbol, map_err = self._reconcile_broker_symbol(canonical)
        if map_err:
            self._logger.warning(map_err)
            log_rejection_event(
                stage="SYMBOL",
                reason=map_err,
                symbol=canonical,
                direction=signal.direction.name if signal.direction else None,
                context={"resolved": broker_symbol or ""},
            )
            return ExecutionResult(success=False, message=map_err)

        from tradingbot.adapters.mt5_health import check_autotrading_ready

        auto_ok, auto_reason = check_autotrading_ready(signal.symbol, config=self._config)
        if not auto_ok:
            self._logger.warning("AutoTrading check failed: %s", auto_reason)
            return ExecutionResult(success=False, message=auto_reason)

        broker_symbol = broker_symbol or self._broker_symbol(signal.symbol)
        mt5_signal = _direction_to_mt5(signal.direction)
        if mt5_signal == 0:
            return ExecutionResult(success=False, message="HOLD — no order")

        price = _current_price(broker_symbol, mt5_signal)
        if price <= 0:
            return ExecutionResult(success=False, message=f"No price for {broker_symbol}")

        strategy = signal.strategy_name or "kernel"
        return self._place_market_order(
            broker_symbol,
            mt5_signal,
            lot,
            price,
            strategy,
            signal.stop_loss,
            signal.take_profit,
            trade_signal=signal,
        )

    def _reconcile_broker_symbol(self, canonical: str) -> tuple[str | None, str | None]:
        """Strict symbol mapping check before live order send."""
        import MetaTrader5 as mt5

        broker_symbol = resolve_broker_symbol(canonical, self._config)
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            return None, f"SYMBOL_MAPPING_INVALID canonical={canonical} resolved={broker_symbol}"
        if not info.visible:
            mt5.symbol_select(broker_symbol, True)
            info = mt5.symbol_info(broker_symbol)
        if info is None or not info.visible:
            return None, f"SYMBOL_MAPPING_INVALID canonical={canonical} resolved={broker_symbol}"
        trade_mode = getattr(info, "trade_mode", None)
        disabled = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)
        if trade_mode is not None and trade_mode == disabled:
            return None, f"SYMBOL_MAPPING_INVALID canonical={canonical} resolved={broker_symbol}"
        self._broker_symbols[canonical] = broker_symbol
        return broker_symbol, None

    def _quote_price(self, signal: TradingSignal) -> float:
        try:
            import MetaTrader5 as mt5

            broker_symbol = self._broker_symbol(signal.symbol)
            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                return 0.0
            return float(tick.ask if signal.direction == SignalDirection.BUY else tick.bid)
        except Exception:
            return 0.0

    def _place_market_order(
        self,
        symbol: str,
        side: int,
        lot: float,
        price: float,
        strategy: str,
        sl: float | None,
        tp: float | None,
        *,
        trade_signal: TradingSignal | None = None,
    ) -> ExecutionResult:
        import MetaTrader5 as mt5

        ok, reason = order_logic.validate_order(symbol, symbol, side, lot, price)
        if not ok:
            self._logger.warning("Order rejected: %s", reason)
            return ExecutionResult(success=False, message=reason)

        ok, reason = order_logic.check_order_risk(symbol, lot, price)
        if not ok:
            self._logger.warning("Order rejected: %s", reason)
            return ExecutionResult(success=False, message=reason)

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return ExecutionResult(success=False, message=f"Symbol {symbol} not found")

        type_filling = _filling_constant(mt5, symbol_info.filling_mode)
        order_type = mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL

        request: dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "deviation": _DEVIATION,
            "magic": _MAGIC,
            "comment": _mt5_comment(strategy, trade_signal.timeframe if trade_signal else ""),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": type_filling,
        }
        if sl is not None and sl > 0:
            request["sl"] = sl
        if tp is not None and tp > 0:
            request["tp"] = tp

        result = _order_send_with_retry(mt5, request, self._config, symbol)

        if result is None:
            try:
                from tradingbot.services.phase51a_forward_cert import is_phase51a_enabled, log_order_send_failure

                if is_phase51a_enabled() and trade_signal is not None:
                    log_order_send_failure(
                        symbol=trade_signal.symbol,
                        direction=trade_signal.direction.name,
                        message=f"order_send returned None: {mt5.last_error()}",
                    )
            except Exception:
                pass
            return ExecutionResult(
                success=False, message=f"order_send returned None: {mt5.last_error()}"
            )

        if result.retcode in (mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_PLACED", 10009)):
            fill_price = float(getattr(result, "price", price) or price)
            slip_pips = abs(fill_price - price) / pip_size(symbol)
            self._logger.info(
                "Order executed: %s %s %s lots @ %s (slip=%.2f pips)",
                symbol,
                side,
                lot,
                fill_price,
                slip_pips,
            )
            if trade_signal is not None:
                from tradingbot.adapters.risk_gate import record_live_entry

                record_live_entry(trade_signal.timeframe)
                self._journal.log_execution(
                    mode=mode_label(),
                    symbol=trade_signal.symbol,
                    timeframe=trade_signal.timeframe,
                    direction=trade_signal.direction.name,
                    lot=lot,
                    requested_price=price,
                    fill_price=fill_price,
                    slippage_pips=round(slip_pips, 3),
                    sl=sl,
                    tp=tp,
                    ticket=int(getattr(result, "order", 0) or 0),
                    success=True,
                    message="executed",
                )
                try:
                    from tradingbot.services.phase51a_forward_cert import (
                        is_phase51a_enabled,
                        log_trade_entry,
                    )

                    if is_phase51a_enabled():
                        ticket_id = int(getattr(result, "order", 0) or getattr(result, "deal", 0) or 0)
                        if ticket_id:
                            log_trade_entry(
                                ticket=ticket_id,
                                signal=trade_signal,
                                fill_price=fill_price,
                                lot=lot,
                            )
                except Exception:
                    pass
                try:
                    from tradingbot.services.engine_telemetry import get_engine_telemetry, resolve_engine_from_signal

                    ticket_id = int(getattr(result, "order", 0) or getattr(result, "deal", 0) or 0)
                    if ticket_id and trade_signal is not None:
                        get_engine_telemetry(self._config.get("BASE_DIR")).record_trade_open(
                            resolve_engine_from_signal(trade_signal),
                            ticket=ticket_id,
                            symbol=trade_signal.symbol,
                            direction=trade_signal.direction.name,
                            entry_price=fill_price,
                            lot=lot,
                        )
                except Exception:
                    pass
                try:
                    from tradingbot.ml.integration.config import is_ml_shadow_enabled
                    from tradingbot.ml.shadow.shadow_observer import (
                        get_last_shadow_cycle,
                        record_shadow_entry_from_cycle,
                    )

                    if is_ml_shadow_enabled():
                        ticket_id = int(getattr(result, "order", 0) or getattr(result, "deal", 0) or 0)
                        if ticket_id:
                            cycle = get_last_shadow_cycle(trade_signal.symbol, trade_signal.timeframe)
                            record_shadow_entry_from_cycle(
                                ticket=ticket_id,
                                symbol=trade_signal.symbol,
                                timeframe=trade_signal.timeframe,
                                live_engine_direction=trade_signal.direction.name,
                                cycle=cycle,
                            )
                except Exception:
                    pass
                from tradingbot.services.notifier import Notifier

                Notifier(self._config.get("BASE_DIR", ".")).alert(
                    "info",
                    f"TRADE {trade_signal.direction.name} {trade_signal.symbol} "
                    f"lot={lot} ticket={int(getattr(result, 'order', 0) or 0)} "
                    f"slip={round(slip_pips, 2)}p",
                )
            return ExecutionResult(
                success=True, ticket=result.order, message="Order executed successfully"
            )

        self._logger.error("Order failed: %s - %s", result.retcode, result.comment)
        try:
            from tradingbot.services.phase51a_forward_cert import is_phase51a_enabled, log_order_send_failure

            if is_phase51a_enabled() and trade_signal is not None:
                log_order_send_failure(
                    symbol=trade_signal.symbol,
                    direction=trade_signal.direction.name,
                    message=f"MT5 error: {result.retcode} - {result.comment}",
                )
        except Exception:
            pass
        return ExecutionResult(
            success=False, message=f"MT5 error: {result.retcode} - {result.comment}"
        )

    def manage_open_positions(self, market_key: str) -> None:
        try:
            import MetaTrader5 as mt5

            symbol_part = market_key.split(":")[0]
            broker_symbol = self._broker_symbol(symbol_part)
            positions = mt5.positions_get(symbol=broker_symbol)
            count = len(positions) if positions else 0
            if count:
                logger.debug("Open positions %s: %d", broker_symbol, count)
        except Exception as e:
            logger.debug("manage_open_positions: %s", e)


_RETRY_CODES = frozenset({10004, 10006, 10007, 10010, 10021, 10031})


def _order_send_with_retry(mt5: Any, request: dict[str, Any], config: dict[str, Any], symbol: str) -> Any:
    import time

    from tradingbot.services.mt5_order_guard import guarded_order_send

    result = None
    for attempt in range(2):
        t0 = time.perf_counter()
        result = guarded_order_send(mt5, request, label="Mt5ExecutionAdapter")
        elapsed = time.perf_counter() - t0
        if elapsed > 2.0:
            logger.warning(
                "MT5 order_send slow | symbol=%s volume=%s elapsed=%.2fs",
                request.get("symbol", symbol),
                request.get("volume", "?"),
                elapsed,
            )
        if result is not None and result.retcode not in _RETRY_CODES:
            return result
        if attempt == 0:
            ensure_mt5_connected(config)
            mt5.symbol_select(symbol, True)
            time.sleep(0.5)
            tick = mt5.symbol_info_tick(symbol)
            if tick is not None:
                is_buy = request.get("type") == mt5.ORDER_TYPE_BUY
                request["price"] = float(tick.ask if is_buy else tick.bid)
    return result


def _mt5_comment(strategy: str, timeframe: str = "") -> str:
    from tradingbot.domain.position_preset import normalize_tf

    tf = normalize_tf(timeframe or "M15")
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in (strategy or "kernel"))
    return f"TB_{tf}_{safe}"[:31]


def _filling_constant(mt5: Any, filling_flag: int) -> Any:
    name = order_logic.filling_mode_name(filling_flag)
    return {
        "FOK": mt5.ORDER_FILLING_FOK,
        "IOC": mt5.ORDER_FILLING_IOC,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }[name]


def _direction_to_mt5(direction: SignalDirection) -> int:
    if direction == SignalDirection.BUY:
        return 1
    if direction == SignalDirection.SELL:
        return -1
    return 0


def _current_price(symbol: str, signal: int) -> float:
    import MetaTrader5 as mt5

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return 0.0
    return float(tick.ask if signal == 1 else tick.bid)
