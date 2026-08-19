"""
Kill Switch — توقف اضطراری هسته در صورت نقض حد drawdown یا ضرر روزانه.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tradingbot.kernel.trading_kernel import TradingKernel

logger = logging.getLogger(__name__)


class KillSwitchService:
    def __init__(
        self,
        kernel: "TradingKernel",
        config: dict[str, Any] | None = None,
        *,
        check_interval_seconds: int = 30,
    ) -> None:
        self._kernel = kernel
        self._config = config or {}
        sc = self._config.get("PRICE_ACTION", {})
        conditions = self._config.get("EMERGENCY_STOP_CONDITIONS", {})

        self._enabled = bool(self._config.get("EMERGENCY_STOP_ENABLED", True))
        self._max_dd = float(sc.get("MAX_DRAWDOWN_PCT", conditions.get("max_drawdown", 0.15)))
        self._dd_buffer = float(self._config.get("KILL_SWITCH_DD_BUFFER", 0.85))
        self._max_daily_loss = float(
            sc.get("MAX_DAILY_LOSS_PCT", conditions.get("max_daily_loss", 0.04))
        )
        self._use_equity_daily = bool(self._config.get("KILL_SWITCH_USE_EQUITY_DAILY", True))
        self._day_reset_hour_utc = int(self._config.get("KILL_SWITCH_DAY_RESET_HOUR_UTC", 0))
        self._interval = check_interval_seconds

        self._peak_equity = 0.0
        self._day_start_equity: float | None = None
        self._day_key: str | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        if not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(
            "KillSwitch started | max_dd=%.0f%% (buffer=%.0f%%) daily_loss=%.0f%%",
            self._max_dd * 100,
            self._dd_buffer * 100,
            self._max_daily_loss * 100,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        import time

        while self._running:
            try:
                self._check()
            except Exception as e:
                logger.debug("KillSwitch check error: %s", e)
            time.sleep(self._interval)

    def _check(self) -> None:
        equity, balance, daily_pnl = self._read_account()
        if equity <= 0:
            return

        self._peak_equity = max(self._peak_equity, equity)
        if self._peak_equity > 0:
            dd = (self._peak_equity - equity) / self._peak_equity
            trigger_dd = self._max_dd * self._dd_buffer
            if dd >= trigger_dd:
                self._trigger(
                    f"drawdown {dd*100:.1f}% >= {trigger_dd*100:.1f}% "
                    f"(limit {self._max_dd*100:.0f}% × buffer {self._dd_buffer:.2f})"
                )
                return

        day_base = self._day_start_equity or equity
        if daily_pnl <= -day_base * self._max_daily_loss:
            self._trigger(
                f"daily loss {daily_pnl:.2f} (limit {day_base * self._max_daily_loss:.2f})"
            )

    def _trigger(self, reason: str) -> None:
        logger.critical("KILL SWITCH: %s", reason)
        try:
            from tradingbot.services.notifier import Notifier

            base = self._config.get("BASE_DIR", ".")
            Notifier(base).alert("critical", f"KILL SWITCH: {reason}")
        except Exception:
            pass
        self._kernel.emergency_stop(reason)
        self._close_all_positions()
        self._running = False

    def _close_all_positions(self) -> None:
        try:
            import MetaTrader5 as mt5

            from tradingbot.services.mt5_order_guard import guarded_order_send

            positions = mt5.positions_get()
            if not positions:
                return
            for pos in positions:
                tick = mt5.symbol_info_tick(pos.symbol)
                if tick is None:
                    continue
                close_type = (
                    mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
                )
                price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": price,
                    "deviation": 20,
                    "magic": pos.magic,
                    "comment": "kill_switch",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                guarded_order_send(mt5, request, label="KillSwitch")
        except Exception as e:
            logger.error("Kill switch close failed: %s", e)

    def _utc_day_key(self) -> str:
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        if now.hour < self._day_reset_hour_utc:
            now = now - timedelta(days=1)
        return now.strftime("%Y-%m-%d")

    def _read_account(self) -> tuple[float, float, float]:
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
            if info is None:
                return 0.0, 0.0, 0.0

            equity = float(info.equity)
            balance = float(info.balance)
            day_key = self._utc_day_key()
            if self._day_key != day_key:
                self._day_key = day_key
                self._day_start_equity = equity
                self._peak_equity = equity

            base = self._day_start_equity or equity
            ref = equity if self._use_equity_daily else balance
            daily_pnl = ref - base
            return equity, balance, daily_pnl
        except Exception:
            return 0.0, 0.0, 0.0
