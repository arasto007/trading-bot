"""
آداپتر مدیریت پوزیشن MT5 — هسته‌محور.

این ماژول منطق پراکنده‌ی پروژه‌ی قدیم را یکجا و تمیز بازسازی می‌کند:
- ``TradingBot.manage_trailing_stop`` / ``_calculate_aggressive_sl``  (trailing پلکانی ATR-Based)
- ``TradingBot._check_emergency_stop``                                 (حد ضرر اضطراری)
- ``PartialTPManager`` / ``PositionProtector._check_partial_tp``       (برداشت سود پله‌ای)

منطق محاسباتی (trailing/partial) در ``tradingbot.domain.position_logic`` است تا
با بک‌تست دقیقاً یکسان باشد.

پیاده‌سازی: ports.IPositionManager
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tradingbot.services.mt5_order_guard import guarded_order_send
from tradingbot.domain.position_logic import (
    DEFAULT_PARTIAL_TP_LEVELS,
    calculate_safe_sl,
    partial_tp_target,
    pip_size,
    target_hit,
    trailing_improves,
)
from tradingbot.domain.position_preset import (
    parse_timeframe_from_comment,
    partial_tp_enabled,
)
from tradingbot.domain.session_logic import should_eod_close, should_friday_close
from tradingbot.ports.position_manager import IPositionManager
from tradingbot.adapters.legacy_loader import ensure_legacy_path, load_legacy_config

logger = logging.getLogger(__name__)


class Mt5PositionManager(IPositionManager):
    """
    مدیریت کامل پوزیشن‌های باز از مسیر هسته.

    در هر چرخه برای هر پوزیشن باز:
      1) بررسی حد ضرر اضطراری (بستن فوری)
      2) برداشت سود پله‌ای (Partial TP بر اساس مضرب R)
      3) Trailing Stop پلکانی ATR-Based (هرگز شل نمی‌شود)

    حالت dry-run: با متغیر محیطی ``TRADINGBOT_DRY_RUN`` فقط لاگ می‌کند و
    هیچ سفارشی به بروکر ارسال نمی‌شود.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        enable_trailing: bool = True,
        enable_partial_tp: bool = True,
        enable_emergency: bool = True,
        emergency_max_loss_pips: float = 50.0,
        partial_tp_levels: tuple[tuple[float, float], ...] = DEFAULT_PARTIAL_TP_LEVELS,
    ) -> None:
        from tradingbot.infra.logging import get_logger

        self._config = config or load_legacy_config()
        base_dir = self._config.get("BASE_DIR", ".")
        self._logger = get_logger("position_manager", base_dir)

        cfg_emergency = self._config.get(
            "EMERGENCY_MAX_LOSS_PIPS",
            self._config.get("emergency_max_loss_pips"),
        )

        self.enable_trailing = enable_trailing
        self.enable_partial_tp = enable_partial_tp
        self.enable_emergency = enable_emergency
        self.emergency_max_loss_pips = float(
            cfg_emergency if cfg_emergency is not None else emergency_max_loss_pips
        )
        self.partial_tp_levels = partial_tp_levels

        pa = self._config.get("PRICE_ACTION", {})
        self.eod_close_enabled = bool(
            self._config.get("EOD_CLOSE_ENABLED", pa.get("EOD_CLOSE_ENABLED", True))
        )
        self.eod_hour = int(self._config.get("EOD_HOUR", pa.get("EOD_HOUR", 21)))
        self.eod_minute = int(self._config.get("EOD_MINUTE", pa.get("EOD_MINUTE", 55)))
        self.trail_atr_mult = float(pa.get("TRAILING_ATR_MULT", 2.0))
        self.friday_close_enabled = bool(pa.get("FRIDAY_CLOSE_ENABLED", True))
        self.friday_close_hour = int(pa.get("FRIDAY_CLOSE_HOUR", 20))
        self.friday_close_minute = int(pa.get("FRIDAY_CLOSE_MINUTE", 0))

        # رجیستری درون‌حافظه‌ای برای ردیابی Partial TP و ریسک اولیه‌ی هر تیکت.
        self._registry: dict[int, dict[str, Any]] = {}

    @property
    def dry_run(self) -> bool:
        from tradingbot.services.mt5_order_guard import blocks_broker_orders

        return blocks_broker_orders()

    # ------------------------------------------------------------------ public
    def manage_all(self) -> None:
        ensure_legacy_path()
        import MetaTrader5 as mt5  # noqa: E402

        try:
            positions = mt5.positions_get()
        except Exception as e:  # pragma: no cover - وابسته به ترمینال
            self._logger.debug(f"[POS_MGR] positions_get failed: {e}")
            return

        if not positions:
            self._registry.clear()
            return

        live_tickets = {p.ticket for p in positions}
        for ticket in list(self._registry.keys()):
            if ticket not in live_tickets:
                self._registry.pop(ticket, None)

        for position in positions:
            try:
                self._manage_one(position)
            except Exception as e:
                self._logger.error(f"[POS_MGR] error on {position.ticket}: {e}")

    # ----------------------------------------------------------------- private
    def _manage_one(self, position: Any) -> None:
        import MetaTrader5 as mt5  # noqa: E402

        symbol = position.symbol
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return
        is_buy = position.type == mt5.ORDER_TYPE_BUY
        current_price = tick.bid if is_buy else tick.ask

        self._register_if_new(position)

        if self.friday_close_enabled and self._check_friday_close(position, current_price):
            return
        if self.eod_close_enabled and self._check_eod_close(position, current_price):
            return

        if self.enable_emergency and self._check_emergency(position, current_price, is_buy):
            return

        if self._is_xauusd(symbol):
            self._manage_xauusd_intelligence(position, current_price, is_buy, tick)
            return

        if self._partial_tp_enabled_for(position) and self._check_partial_tp(
            position, current_price, is_buy
        ):
            return

        if self.enable_trailing:
            self._apply_trailing(position, current_price, is_buy)

    def _is_xauusd(self, symbol: str) -> bool:
        return str(symbol or "").upper().startswith("XAU")

    def _account_equity(self) -> float:
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
            if info is not None:
                return float(info.equity)
        except Exception:
            pass
        return 0.0

    def _resolve_pm_profile(self):
        from tradingbot.adapters.risk_gate import detect_account_tier, resolve_position_management_profile

        tier = detect_account_tier(self._account_equity())
        phase52a = os.getenv("PHASE52A_PM", "").strip().lower() in ("1", "true", "yes", "on")
        return resolve_position_management_profile(tier, phase52a=phase52a), tier

    @staticmethod
    def _current_r(is_buy: bool, entry: float, current_price: float, risk: float) -> float:
        if risk <= 0:
            return 0.0
        move = (current_price - entry) if is_buy else (entry - current_price)
        return move / risk

    def _manage_xauusd_intelligence(
        self, position: Any, current_price: float, is_buy: bool, tick: Any
    ) -> None:
        data = self._registry.get(position.ticket)
        if not data:
            return
        profile, _tier = self._resolve_pm_profile()
        entry = data["entry"]
        risk = data["initial_risk"]
        current_r = self._current_r(is_buy, entry, current_price, risk)

        try:
            from tradingbot.services.phase51a_forward_cert import is_phase51a_enabled, update_trade_excursion

            if is_phase51a_enabled():
                update_trade_excursion(ticket=int(position.ticket), current_r=current_r)
        except Exception:
            pass

        if profile.time_exit_enabled and self._check_stagnation_exit(
            position, current_price, is_buy, current_r, profile
        ):
            return
        if profile.breakeven_enabled and self._apply_breakeven(
            position, current_price, is_buy, tick, data, current_r, profile
        ):
            return
        if profile.partial_close_enabled and self._apply_partial_close_36a(
            position, current_price, is_buy, data, current_r, profile
        ):
            return
        if profile.atr_trailing_enabled:
            self._apply_atr_trailing_36a(position, current_price, is_buy, data, current_r, profile)

    def _m5_bars_since_open(self, position: Any) -> int:
        import MetaTrader5 as mt5
        from datetime import datetime, timezone

        try:
            open_time = datetime.fromtimestamp(position.time, tz=timezone.utc)
            rates = mt5.copy_rates_from(position.symbol, mt5.TIMEFRAME_M5, open_time, 500)
            if rates is None or len(rates) <= 1:
                return 0
            return max(0, len(rates) - 1)
        except Exception:
            return 0

    def _check_stagnation_exit(
        self,
        position: Any,
        current_price: float,
        is_buy: bool,
        current_r: float,
        profile: Any,
    ) -> bool:
        bars = self._m5_bars_since_open(position)
        if bars < profile.stagnation_bars_limit:
            return False
        if current_r >= profile.stagnation_min_profit_r:
            return False
        self._logger.info(
            "[STAGNATION] closing %s after %d M5 bars at %.2fR (< %.2fR)",
            position.ticket,
            bars,
            current_r,
            profile.stagnation_min_profit_r,
        )
        self._close_position(position, comment="KernelStagnationExit")
        return True

    def _apply_breakeven(
        self,
        position: Any,
        current_price: float,
        is_buy: bool,
        tick: Any,
        data: dict[str, Any],
        current_r: float,
        profile: Any,
    ) -> bool:
        if data.get("breakeven_done"):
            return False
        if current_r < profile.breakeven_trigger_r:
            return False

        spread = max(float(tick.ask) - float(tick.bid), pip_size(position.symbol))
        entry = data["entry"]
        new_sl = entry + spread if is_buy else entry - spread
        original_sl = position.sl
        if is_buy and original_sl > 0 and new_sl <= original_sl:
            data["breakeven_done"] = True
            return False
        if not is_buy and original_sl > 0 and new_sl >= original_sl:
            data["breakeven_done"] = True
            return False

        if self._modify_stop_loss(position, new_sl, label="Breakeven36A"):
            data["breakeven_done"] = True
            self._logger.info(
                "[BE36A] %s moved SL to breakeven+spread at %.2fR", position.ticket, current_r
            )
            return True
        return False

    def _apply_partial_close_36a(
        self,
        position: Any,
        current_price: float,
        is_buy: bool,
        data: dict[str, Any],
        current_r: float,
        profile: Any,
    ) -> bool:
        if data.get("partial_36a_done"):
            return False
        if current_r < profile.partial_trigger_r:
            return False

        volume = float(position.volume)
        if volume <= 0.01 + 1e-9:
            data["partial_36a_done"] = True
            self._logger.info(
                "[PARTIAL36A] skip %s — volume %.2f at min lot", position.ticket, volume
            )
            return False

        close_volume = round(volume * float(getattr(profile, "partial_fraction", 0.5) or 0.5), 2)
        remaining = round(volume - close_volume, 2)
        if remaining < 0.01:
            data["partial_36a_done"] = True
            self._logger.info(
                "[PARTIAL36A] skip %s — remaining %.2f below min lot", position.ticket, remaining
            )
            return False

        if self._close_partial_volume(
            position,
            close_volume,
            comment=f"KernelPartial {profile.partial_trigger_r}R 50%",
        ):
            data["partial_36a_done"] = True
            data["remaining_volume"] = remaining
            self._logger.info(
                "[PARTIAL36A] closed 50%% (%.2f) of %s at %.2fR",
                close_volume,
                position.ticket,
                current_r,
            )
            try:
                from tradingbot.services.phase47c_forward_tracker import log_phase47c_event

                log_phase47c_event(
                    "partial_hit",
                    ticket=int(position.ticket),
                    volume=round(close_volume, 4),
                    r_multiple=round(current_r, 4),
                )
            except Exception:
                pass
            return True
        return False

    def _apply_atr_trailing_36a(
        self,
        position: Any,
        current_price: float,
        is_buy: bool,
        data: dict[str, Any],
        current_r: float,
        profile: Any,
    ) -> None:
        if getattr(profile, "trailing_requires_partial", False) and not data.get("partial_36a_done"):
            return
        if current_r < profile.trailing_trigger_r:
            return

        tf = data.get("timeframe") or "M5"
        atr = self._calculate_atr_for_timeframe(position.symbol, tf)
        pip = pip_size(position.symbol)
        if atr <= 0:
            atr = pip * 10

        from tradingbot.domain.professional_pm import trail_distance

        min_pips = float(getattr(profile, "trailing_min_pips", 0.0) or 0.0)
        if min_pips > 0:
            trail_dist = trail_distance(
                atr=atr,
                pip=pip,
                atr_multiplier=profile.trailing_atr_multiplier,
                min_pips=min_pips,
            )
        else:
            trail_dist = profile.trailing_atr_multiplier * atr

        original_sl = float(position.sl or 0.0)
        if is_buy:
            new_sl = current_price - trail_dist
            min_improve = original_sl + 0.1 * atr if min_pips <= 0 else original_sl
            if new_sl <= min_improve:
                return
        else:
            new_sl = current_price + trail_dist
            if original_sl <= 0:
                min_improve = new_sl
            else:
                min_improve = original_sl - 0.1 * atr if min_pips <= 0 else original_sl
            if new_sl >= min_improve:
                return

        if not trailing_improves(is_buy, original_sl, new_sl):
            return

        label = "Trail52A" if min_pips > 0 else "Trail36A"
        if self._modify_stop_loss(position, new_sl, label=label):
            data["trailing_36a_active"] = True
            self._logger.info(
                "[TRAIL36A] %s SL -> %.5f at %.2fR (trail %.1fxATR)",
                position.ticket,
                new_sl,
                current_r,
                profile.trailing_atr_multiplier,
            )
            try:
                from tradingbot.services.phase47c_forward_tracker import log_phase47c_event

                log_phase47c_event(
                    "trailing_hit",
                    ticket=int(position.ticket),
                    new_sl=round(new_sl, 5),
                    r_multiple=round(current_r, 4),
                )
            except Exception:
                pass

    def _calculate_atr_for_timeframe(self, symbol: str, timeframe: str, period: int = 14) -> float:
        import MetaTrader5 as mt5

        tf_key = str(timeframe or "M5").upper()
        tf_map = {
            "M5": mt5.TIMEFRAME_M5,
            "5M": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "15M": mt5.TIMEFRAME_M15,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
        }
        tf = tf_map.get(tf_key, mt5.TIMEFRAME_M5)
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, period + 2)
            if rates is None or len(rates) < period + 1:
                return 0.0
            trs = []
            for i in range(1, len(rates)):
                high = rates[i]["high"]
                low = rates[i]["low"]
                prev_close = rates[i - 1]["close"]
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
            if not trs:
                return 0.0
            return float(sum(trs[-period:]) / min(period, len(trs)))
        except Exception:
            return 0.0

    def _modify_stop_loss(self, position: Any, new_sl: float, *, label: str) -> bool:
        import MetaTrader5 as mt5

        if self.dry_run:
            self._logger.info(
                "[DRY_RUN][%s] %s SL %.5f -> %.5f", label, position.ticket, position.sl, new_sl
            )
            return True

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": position.symbol,
            "position": position.ticket,
            "sl": new_sl,
            "tp": position.tp,
        }
        result = guarded_order_send(mt5, request, label=f"PositionManager.{label}")
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        msg = result.comment if result else "unknown"
        self._logger.error("[%s] failed on %s: %s", label, position.ticket, msg)
        return False

    def _close_partial_volume(self, position: Any, close_volume: float, *, comment: str) -> bool:
        import MetaTrader5 as mt5

        close_volume = round(max(0.01, close_volume), 2)
        if close_volume >= float(position.volume):
            return False

        if self.dry_run:
            self._logger.info(
                "[DRY_RUN][PARTIAL36A] would close %.2f of %s", close_volume, position.ticket
            )
            return True

        close_type = (
            mt5.ORDER_TYPE_SELL
            if position.type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": close_volume,
            "type": close_type,
            "position": position.ticket,
            "comment": comment,
        }
        result = guarded_order_send(mt5, request, label="PositionManager.partial_36a")
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return True
        msg = result.comment if result else "unknown"
        self._logger.error("[PARTIAL36A] failed on %s: %s", position.ticket, msg)
        return False

    def _register_if_new(self, position: Any) -> None:
        ticket = position.ticket
        if ticket in self._registry:
            return
        pip = pip_size(position.symbol)
        entry = position.price_open
        if position.sl and position.sl > 0:
            initial_risk = abs(entry - position.sl)
        else:
            atr = self._calculate_atr(position.symbol)
            initial_risk = atr if atr > 0 else 15 * pip
        self._registry[ticket] = {
            "entry": entry,
            "initial_risk": max(initial_risk, pip),
            "original_volume": position.volume,
            "remaining_volume": position.volume,
            "hits": [False] * len(self.partial_tp_levels),
            "timeframe": self._resolve_timeframe(position),
            "enable_partial_tp": None,
            "breakeven_done": False,
            "partial_36a_done": False,
            "trailing_36a_active": False,
        }
        data = self._registry[ticket]
        data["enable_partial_tp"] = self._partial_tp_enabled_for(position, data)

    def _logical_symbol(self) -> str:
        from tradingbot.config.live import PRIMARY_SYMBOL

        symbols = self._config.get("SYMBOLS") or self._config.get("symbols") or [PRIMARY_SYMBOL]
        if isinstance(symbols, list) and symbols:
            return str(symbols[0])
        return PRIMARY_SYMBOL

    def _resolve_timeframe(self, position: Any) -> str | None:
        tf = parse_timeframe_from_comment(getattr(position, "comment", "") or "")
        if tf:
            return tf
        ticket = int(getattr(position, "ticket", 0) or 0)
        if ticket <= 0:
            return None
        try:
            from tradingbot.services.trade_journal import TradeJournal

            base = self._config.get("BASE_DIR", ".")
            journal = TradeJournal(base)
            with journal._connect() as conn:
                row = conn.execute(
                    "SELECT timeframe FROM executions WHERE ticket=? ORDER BY id DESC LIMIT 1",
                    (ticket,),
                ).fetchone()
            if row and row["timeframe"]:
                from tradingbot.domain.position_preset import normalize_tf

                return normalize_tf(str(row["timeframe"]))
        except Exception:
            pass
        return None

    def _partial_tp_enabled_for(
        self, position: Any, registry: dict[str, Any] | None = None
    ) -> bool:
        if not self.enable_partial_tp:
            return False
        data = registry or self._registry.get(position.ticket) or {}
        cached = data.get("enable_partial_tp")
        if cached is not None:
            return bool(cached)
        tf = data.get("timeframe") or self._resolve_timeframe(position)
        if not tf:
            return False
        sym = self._logical_symbol()
        return partial_tp_enabled(sym, tf)

    def _check_friday_close(self, position: Any, current_price: float) -> bool:
        import MetaTrader5 as mt5  # noqa: E402
        from datetime import datetime, timezone

        try:
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                return False
            ts = datetime.fromtimestamp(tick.time, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return False
        if should_friday_close(
            ts,
            close_hour=self.friday_close_hour,
            close_minute=self.friday_close_minute,
        ):
            self._logger.info(f"[FRIDAY] closing {position.ticket} before weekend")
            self._close_position(position, comment="KernelFridayClose")
            return True
        return False

    def _check_eod_close(self, position: Any, current_price: float) -> bool:
        import MetaTrader5 as mt5  # noqa: E402
        from datetime import datetime, timezone

        try:
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                return False
            ts = datetime.fromtimestamp(tick.time, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return False

        if should_eod_close(ts, eod_hour=self.eod_hour, eod_minute=self.eod_minute):
            self._logger.info(f"[EOD] closing {position.ticket} at session end")
            self._close_position(position, comment="KernelEODClose")
            return True
        return False

    # --- emergency stop --------------------------------------------------
    def _check_emergency(self, position: Any, current_price: float, is_buy: bool) -> bool:
        pip = pip_size(position.symbol)
        entry = position.price_open
        loss_pips = (entry - current_price) / pip if is_buy else (current_price - entry) / pip
        if loss_pips > self.emergency_max_loss_pips:
            self._logger.warning(
                f"[EMERGENCY] {position.ticket} loss {loss_pips:.1f} pips "
                f"> {self.emergency_max_loss_pips} → close"
            )
            self._close_position(position)
            return True
        return False

    # --- partial TP ------------------------------------------------------
    def _check_partial_tp(self, position: Any, current_price: float, is_buy: bool) -> bool:
        data = self._registry.get(position.ticket)
        if not data:
            return False
        entry = data["entry"]
        risk = data["initial_risk"]
        for idx, (r_mult, close_pct) in enumerate(self.partial_tp_levels):
            if data["hits"][idx]:
                continue
            target = partial_tp_target(is_buy, entry, risk, r_mult)
            if target_hit(is_buy, current_price, target):
                if self._close_partial(position, data, close_pct, r_mult):
                    data["hits"][idx] = True
                    return True
        return False

    def _close_partial(
        self, position: Any, data: dict[str, Any], close_pct: float, r_mult: float
    ) -> bool:
        import MetaTrader5 as mt5  # noqa: E402

        close_volume = round(data["original_volume"] * close_pct, 2)
        close_volume = max(0.01, close_volume)
        if close_volume >= data["remaining_volume"]:
            close_volume = data["remaining_volume"]

        if self.dry_run:
            self._logger.info(
                f"[DRY_RUN][PARTIAL_TP] would close {close_pct*100:.0f}% "
                f"({close_volume:.2f}) of {position.ticket} at {r_mult:.1f}R"
            )
            data["remaining_volume"] = round(data["remaining_volume"] - close_volume, 2)
            return True

        close_type = (
            mt5.ORDER_TYPE_SELL
            if position.type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": close_volume,
            "type": close_type,
            "position": position.ticket,
            "comment": f"KernelPartialTP {r_mult:.1f}R {close_pct*100:.0f}%",
        }
        result = guarded_order_send(mt5, request, label="PositionManager.partial_tp")
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            data["remaining_volume"] = round(data["remaining_volume"] - close_volume, 2)
            self._logger.info(
                f"[PARTIAL_TP] closed {close_pct*100:.0f}% ({close_volume:.2f}) of "
                f"{position.ticket} at {r_mult:.1f}R | remaining {data['remaining_volume']:.2f}"
            )
            return True
        msg = result.comment if result else "unknown"
        self._logger.error(f"[PARTIAL_TP] failed on {position.ticket}: {msg}")
        return False

    # --- trailing stop ---------------------------------------------------
    def _apply_trailing(self, position: Any, current_price: float, is_buy: bool) -> None:
        pip = pip_size(position.symbol)
        entry = position.price_open
        original_sl = position.sl
        profit_pips = (
            (current_price - entry) / pip if is_buy else (entry - current_price) / pip
        )
        if profit_pips < 0:
            return

        atr = self._calculate_atr(position.symbol)
        atr = atr if atr > 0 else pip * 10
        new_sl = calculate_safe_sl(
            is_buy, entry, current_price, profit_pips, pip, original_sl, atr
        )
        if not trailing_improves(is_buy, original_sl, new_sl):
            return

        self._update_stop_loss(position, new_sl, profit_pips, pip, atr)

    def _update_stop_loss(
        self, position: Any, new_sl: float, profit_pips: float, pip: float, atr: float
    ) -> None:
        import MetaTrader5 as mt5  # noqa: E402

        if self.dry_run:
            self._logger.info(
                f"[DRY_RUN][TRAIL] {position.symbol} {position.ticket}: "
                f"SL {position.sl:.5f} → {new_sl:.5f} | profit {profit_pips:.1f} pips"
            )
            return

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": position.symbol,
            "position": position.ticket,
            "sl": new_sl,
            "tp": position.tp,
        }
        result = guarded_order_send(mt5, request, label="PositionManager.trailing")
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._logger.info(
                f"[TRAIL] {position.symbol} {position.ticket}: "
                f"SL {position.sl:.5f} → {new_sl:.5f} | profit {profit_pips:.1f} pips "
                f"| ATR {atr/pip:.1f} pips"
            )
        else:
            msg = result.comment if result else "unknown"
            self._logger.error(f"[TRAIL] failed on {position.ticket}: {msg}")

    # --- helpers ---------------------------------------------------------
    def _close_position(self, position: Any, *, comment: str = "KernelEmergencyStop") -> None:
        import MetaTrader5 as mt5  # noqa: E402

        if self.dry_run:
            self._logger.info(f"[DRY_RUN][CLOSE] would close {position.ticket} ({comment})")
            return
        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return
        is_buy = position.type == mt5.ORDER_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": position.ticket,
            "price": tick.bid if is_buy else tick.ask,
            "comment": comment,
        }
        result = guarded_order_send(mt5, request, label="PositionManager.close")
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._logger.warning(f"[CLOSE] closed {position.ticket} ({comment})")
        else:
            msg = result.comment if result else "unknown"
            self._logger.error(f"[EMERGENCY] close failed {position.ticket}: {msg}")

    def _calculate_atr(self, symbol: str, period: int = 14) -> float:
        """ATR از روی کندل‌های اخیر M1/M5 — مستقل و خودکفا."""
        import MetaTrader5 as mt5  # noqa: E402

        tf = mt5.TIMEFRAME_M1
        tfs = self._config.get("TIMEFRAMES") or self._config.get("timeframes") or []
        if tfs and str(tfs[0]).lower() in ("1m", "m1"):
            tf = mt5.TIMEFRAME_M1
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, period + 2)
            if rates is None or len(rates) < period + 1:
                return 0.0
            trs = []
            for i in range(1, len(rates)):
                high = rates[i]["high"]
                low = rates[i]["low"]
                prev_close = rates[i - 1]["close"]
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
            if not trs:
                return 0.0
            return float(sum(trs[-period:]) / min(period, len(trs)))
        except Exception:
            return 0.0
