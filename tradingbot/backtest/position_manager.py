"""
مدیریت پوزیشن بک‌تست — همان منطق live روی پوزیشن‌های مجازی.

از ``tradingbot.domain.position_logic`` و ``professional_pm`` استفاده می‌کند.
"""

from __future__ import annotations

import logging
from datetime import datetime

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.models import VirtualPosition
from tradingbot.domain.position_logic import (
    DEFAULT_PARTIAL_TP_LEVELS,
    calculate_safe_sl,
    partial_tp_target,
    pip_size,
    target_hit,
    trailing_improves,
)
from tradingbot.domain.professional_pm import (
    atr_trail_sl,
    breakeven_sl,
    current_r,
    partial_close_volume,
    should_breakeven,
    should_partial,
    should_time_stop,
    should_trail,
)
from tradingbot.domain.session_logic import should_eod_close, should_friday_close

logger = logging.getLogger(__name__)


class BacktestPositionManager:
    def __init__(self, config: BacktestConfig, broker, data_source) -> None:
        self._cfg = config
        self._broker = broker
        self._data = data_source
        self._levels = DEFAULT_PARTIAL_TP_LEVELS

    def manage_all(self) -> None:
        for pos in list(self._broker.open_positions):
            bar = self._data.current_bar(pos.symbol)
            if bar is None:
                continue
            price = float(bar["close"])
            is_buy = pos.is_buy

            self._tick_pm_bar(pos)

            if self._cfg.friday_close_enabled and self._friday_close(pos, price):
                continue
            if self._cfg.enable_eod_close and self._eod_close(pos, price):
                continue
            if self._cfg.enable_emergency and self._emergency(pos, price, is_buy):
                continue

            mode = str(getattr(self._cfg, "position_management_mode", "legacy") or "legacy").lower()
            if mode in ("36a", "52a") and self._is_xauusd(pos.symbol):
                if self._manage_xauusd_pm(pos, bar, price, is_buy, mode):
                    continue
                continue

            if self._cfg.enable_partial_tp and self._partial_tp(pos, price, is_buy):
                if pos.volume <= 0:
                    continue
            if self._cfg.enable_trailing:
                self._trailing(pos, bar, price, is_buy)

    @staticmethod
    def _is_xauusd(symbol: str) -> bool:
        return str(symbol or "").upper().startswith("XAU")

    def _tick_pm_bar(self, pos: VirtualPosition) -> None:
        cursor = self._data.cursor
        if cursor != pos.pm_last_bar_index:
            pos.pm_bars_held += 1
            pos.pm_last_bar_index = cursor

    def _resolve_pm_profile(self, mode: str):
        from tradingbot.adapters.risk_gate import (
            detect_account_tier,
            phase52a_position_management_profile,
            position_management_profile_for_tier,
        )

        tier = detect_account_tier(float(self._cfg.initial_balance))
        if mode == "52a":
            return phase52a_position_management_profile()
        return position_management_profile_for_tier(tier)

    def _manage_xauusd_pm(
        self,
        pos: VirtualPosition,
        bar,
        price: float,
        is_buy: bool,
        mode: str,
    ) -> bool:
        """Returns True if position was fully closed."""
        profile = self._resolve_pm_profile(mode)
        risk = pos.initial_risk
        if risk <= 0:
            return False

        cur_r = current_r(is_buy=is_buy, entry=pos.entry_price, price=price, risk=risk)
        pip = pip_size(pos.symbol)

        if profile.time_exit_enabled and should_time_stop(
            bars_since_open=pos.pm_bars_held,
            current_r=cur_r,
            bars_limit=profile.stagnation_bars_limit,
            min_profit_r=profile.stagnation_min_profit_r,
        ):
            self._broker.close_position(pos, price, "time_stop")
            return True

        if profile.breakeven_enabled and should_breakeven(
            current_r=cur_r,
            trigger_r=profile.breakeven_trigger_r,
            done=pos.pm_breakeven_done,
        ):
            spread = float(getattr(self._cfg, "spread_pips", 2.5) or 2.5) * pip
            new_sl = breakeven_sl(is_buy=is_buy, entry=pos.entry_price, spread=spread)
            if trailing_improves(is_buy, pos.sl, new_sl):
                pos.sl = new_sl
                pos.pm_breakeven_done = True

        if profile.partial_close_enabled and should_partial(
            current_r=cur_r,
            trigger_r=profile.partial_trigger_r,
            done=pos.pm_partial_done,
        ):
            close_vol = partial_close_volume(
                pos.volume,
                fraction=profile.partial_fraction,
                min_lot=self._cfg.min_lot,
            )
            if close_vol > 0:
                self._broker.partial_close(pos, close_vol, price, "partial_52a")
                pos.pm_partial_done = True
                if pos.volume <= 0:
                    return True

        if profile.atr_trailing_enabled and should_trail(
            current_r=cur_r,
            trigger_r=profile.trailing_trigger_r,
            partial_done=pos.pm_partial_done,
            requires_partial=profile.trailing_requires_partial,
        ):
            atr = self._bar_atr_series(pos.symbol, bar, pip)
            new_sl = atr_trail_sl(
                is_buy=is_buy,
                current_price=price,
                original_sl=pos.sl,
                atr=atr,
                pip=pip,
                atr_multiplier=profile.trailing_atr_multiplier,
                min_pips=profile.trailing_min_pips,
            )
            if new_sl is not None:
                pos.sl = new_sl
                pos.pm_trailing_active = True

        return False

    def _bar_atr_series(self, symbol: str, bar, pip: float) -> float:
        return self._bar_atr(bar, pip)

    def _friday_close(self, pos: VirtualPosition, price: float) -> bool:
        ts = self._data.current_time()
        if ts is None:
            return False
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", ""))
            except ValueError:
                return False
        if should_friday_close(
            ts,
            close_hour=self._cfg.friday_close_hour,
            close_minute=self._cfg.friday_close_minute,
        ):
            self._broker.close_position(pos, price, "friday_close")
            return True
        return False

    def _eod_close(self, pos: VirtualPosition, price: float) -> bool:
        ts = self._data.current_time()
        if ts is None:
            return False
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", ""))
            except ValueError:
                return False
        if should_eod_close(ts, eod_hour=self._cfg.eod_hour, eod_minute=self._cfg.eod_minute):
            self._broker.close_position(pos, price, "eod")
            return True
        return False

    def _emergency(self, pos: VirtualPosition, price: float, is_buy: bool) -> bool:
        pip = pip_size(pos.symbol)
        loss_pips = (
            (pos.entry_price - price) / pip if is_buy else (price - pos.entry_price) / pip
        )
        if loss_pips > self._cfg.emergency_max_loss_pips:
            self._broker.close_position(pos, price, "emergency")
            return True
        return False

    def _partial_tp(self, pos: VirtualPosition, price: float, is_buy: bool) -> bool:
        if pos.initial_risk <= 0:
            return False
        if not pos.partial_hits:
            pos.partial_hits = [False] * len(self._levels)
        for idx, (r_mult, close_pct) in enumerate(self._levels):
            if pos.partial_hits[idx]:
                continue
            target = partial_tp_target(is_buy, pos.entry_price, pos.initial_risk, r_mult)
            if target_hit(is_buy, price, target):
                volume = max(self._cfg.min_lot, round(pos.original_volume * close_pct, 2))
                self._broker.partial_close(pos, volume, price, "partial")
                pos.partial_hits[idx] = True
                return True
        return False

    def _trailing(self, pos: VirtualPosition, bar, price: float, is_buy: bool) -> None:
        pip = pip_size(pos.symbol)
        profit_pips = (
            (price - pos.entry_price) / pip if is_buy else (pos.entry_price - price) / pip
        )
        if profit_pips < 0:
            return
        atr = self._bar_atr(bar, pip)
        trail_mult = float(getattr(self._cfg, "trailing_atr_mult", 0) or 0)
        if trail_mult > 0:
            trail_dist = atr * trail_mult
            new_sl = price - trail_dist if is_buy else price + trail_dist
            if trailing_improves(is_buy, pos.sl, new_sl):
                pos.sl = new_sl
            return
        new_sl = calculate_safe_sl(
            is_buy, pos.entry_price, price, profit_pips, pip, pos.sl, atr
        )
        if trailing_improves(is_buy, pos.sl, new_sl):
            pos.sl = new_sl

    @staticmethod
    def _bar_atr(bar, pip: float) -> float:
        for col in ("atr", "ATR", "atr_14"):
            if col in bar.index:
                try:
                    val = float(bar[col])
                    if val > 0:
                        return val
                except Exception:
                    pass
        try:
            return max(float(bar["high"]) - float(bar["low"]), pip * 10)
        except Exception:
            return pip * 10
