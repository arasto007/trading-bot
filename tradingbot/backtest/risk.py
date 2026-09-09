"""
دروازه‌ی ریسک بک‌تست — parity با live (`domain/live_gates` + `adapters/risk_gate`).

max positions (کل + per-symbol)، HTF alignment، spread، خبر، جمعه.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.instrument import resolve_backtest_economics
from tradingbot.domain.broker_economics import lot_from_broker_economics, validate_sl_tp_vs_stops
from tradingbot.ml.research.phase22c.config import compute_daily_loss_budget, load_phase22c_config
from tradingbot.ml.research.phase22c.hold_chain import HoldStage, get_hold_chain, hold_chain_enabled
from tradingbot.domain.live_gates import (
    check_friday_gate,
    check_htf_alignment,
    check_max_positions,
    check_news_gate,
    check_no_opposite_position,
    check_spread_gate,
    count_open_positions,
)
from tradingbot.domain.market_filters import check_market_filters
from tradingbot.domain.models import RiskDecision, TradingSignal
from tradingbot.domain.position_logic import pip_size
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv
from tradingbot.domain.session_logic import variable_spread_pips
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.risk_gate import (
    AccountTier,
    _is_pa_signal,
    detect_account_tier,
    evaluate_micro_feasible_risk,
    execution_profile_for_tier,
)


def _is_regime_kernel_signal(signal: TradingSignal) -> bool:
    name = (signal.strategy_name or "").upper()
    return name in ("VOL_REGIME", "ADAPTIVE_REGIME")


class BacktestRiskGate:
    def __init__(self, config: BacktestConfig, legacy_config: dict | None = None) -> None:
        self._cfg = config
        self._legacy_config = legacy_config or {}
        self._consecutive_losses = 0
        self._pause_until_bar = -1
        self._last_day: str = ""
        self._day_start_balance: float = config.initial_balance
        self.risk_journal: list[dict] = []

    def _daily_loss_limit(self, snapshot: dict) -> float:
        cfg22 = load_phase22c_config()
        balance = float(snapshot.get("balance", self._cfg.initial_balance))
        ref = float(snapshot.get("day_start_balance", self._day_start_balance))
        if ref <= 0:
            ref = balance
        if not cfg22.enabled or not cfg22.use_day_start_balance:
            ref = self._cfg.initial_balance
        return compute_daily_loss_budget(
            reference_balance=ref,
            max_daily_loss_pct=self._cfg.max_daily_loss_pct,
            risk_per_trade=self._cfg.risk_per_trade,
            floor_trades=cfg22.daily_loss_floor_trades,
        )

    def _record_riskgate_block(self, reason: str) -> None:
        if hold_chain_enabled():
            get_hold_chain().record(HoldStage.RISK_GATE, reason=reason)

    def _append_risk_journal(self, diag: dict, *, allowed: bool, reason: str = "") -> None:
        self.risk_journal.append(
            {
                **diag,
                "allowed": allowed,
                "journal_reason": reason or diag.get("rejection_reason", ""),
            }
        )

    def _resolve_lot_for_signal(
        self,
        signal: TradingSignal,
        snapshot: dict,
        *,
        balance: float,
        regime: str,
    ) -> RiskDecision:
        """Tier-aware lot sizing with live MICRO feasibility parity."""
        df = snapshot.get("ohlcv")
        close = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0
        if signal.metadata is None:
            signal.metadata = {}
        signal.metadata.setdefault("entry", close)
        signal.metadata.setdefault("price", close)

        tier = detect_account_tier(balance)
        profile = execution_profile_for_tier(tier)
        requested = (
            float(profile.risk_per_trade_override)
            if profile.risk_per_trade_override is not None
            else float(self._cfg.risk_per_trade)
        )

        if tier == AccountTier.MICRO:
            ohlcv = df if isinstance(df, pd.DataFrame) else None
            micro_decision, lot, diag = evaluate_micro_feasible_risk(
                signal,
                balance,
                tier=tier,
                requested_risk_pct=requested,
                min_lot=self._cfg.min_lot,
                max_lot=self._cfg.max_lot,
                ohlcv=ohlcv,
                adapt_stop=True,
                log_rejections=True,
            )
            if micro_decision is not None:
                self._record_riskgate_block(diag.get("rejection_reason") or micro_decision.reason)
                self._append_risk_journal(diag, allowed=False, reason=micro_decision.reason)
                return micro_decision
            self._append_risk_journal(diag, allowed=True)
            return RiskDecision(allowed=True, adjusted_lot=lot)

        lot = self._position_size(
            balance,
            close,
            signal.stop_loss,
            signal.symbol,
            regime=regime,
            risk_pct=requested,
        )
        if lot <= 0:
            self._record_riskgate_block("lot too small")
            return RiskDecision(allowed=False, reason="lot too small")
        return RiskDecision(allowed=True, adjusted_lot=lot)

    def evaluate(self, signal: TradingSignal, snapshot: dict) -> RiskDecision:
        symbol = signal.symbol
        open_positions = snapshot.get("open_positions", [])

        open_total = count_open_positions(open_positions)
        open_sym = count_open_positions(open_positions, symbol=symbol)
        ok, reason = check_max_positions(
            open_total,
            open_sym,
            max_total=self._cfg.max_open_positions_total,
            max_per_symbol=self._cfg.max_positions_per_symbol,
        )
        if not ok:
            self._record_riskgate_block(reason)
            return RiskDecision(allowed=False, reason=reason)

        balance = float(snapshot.get("balance", self._cfg.initial_balance))
        cursor = int(snapshot.get("cursor", 0))

        if balance < self._cfg.initial_balance * self._cfg.min_balance_pct:
            self._record_riskgate_block("min balance breached")
            return RiskDecision(allowed=False, reason="min balance breached")

        if cursor < self._pause_until_bar:
            self._record_riskgate_block("cooldown after losses")
            return RiskDecision(allowed=False, reason="cooldown after losses")

        day = str(snapshot.get("current_day", ""))
        if day and day != self._last_day:
            self._last_day = day
            self._consecutive_losses = 0
            self._day_start_balance = balance

        daily_pnl = float(snapshot.get("daily_pnl", 0.0))
        max_daily_loss = self._daily_loss_limit(snapshot)
        if daily_pnl <= -max_daily_loss:
            self._record_riskgate_block("daily loss limit")
            return RiskDecision(allowed=False, reason="daily loss limit")

        trades_today = int(snapshot.get("trades_today", 0))
        if self._cfg.max_trades_per_day > 0 and trades_today >= self._cfg.max_trades_per_day:
            self._record_riskgate_block("max trades per day")
            return RiskDecision(allowed=False, reason="max trades per day")

        last_exit_bar = snapshot.get("last_exit_bar")
        if last_exit_bar is not None and cursor - int(last_exit_bar) < self._cfg.cooldown_bars:
            return RiskDecision(allowed=False, reason="entry cooldown")

        current_time = self._as_datetime(snapshot.get("current_time"))
        if current_time is not None:
            ok, reason = check_friday_gate(
                current_time, no_entry_after_hour=self._cfg.friday_no_entry_after_hour
            )
            if not ok:
                return RiskDecision(allowed=False, reason=reason)

            ok, reason = check_news_gate(
                current_time,
                enabled=self._cfg.use_news_filter,
                minutes=self._cfg.news_blackout_minutes,
            )
            if not ok:
                return RiskDecision(allowed=False, reason=reason)

            hour = current_time.hour if hasattr(current_time, "hour") else 12
            est_spread = (
                variable_spread_pips(self._cfg.spread_pips, hour)
                if self._cfg.variable_spread
                else self._cfg.spread_pips
            )
            ok, reason = check_spread_gate(est_spread, self._cfg.max_spread_pips)
            if not ok:
                return RiskDecision(allowed=False, reason=reason)

        direction = (
            1
            if signal.direction.name == "BUY"
            else -1
            if signal.direction.name == "SELL"
            else 0
        )
        if not _is_regime_kernel_signal(signal):
            htf_bias = int(snapshot.get("htf_bias", 0) or 0)
            tf = (signal.timeframe or self._cfg.timeframe or "").upper()
            require_htf = (
                (tf in ("M5", "5M") and self._cfg.require_htf_alignment_m5)
                or (tf in ("M15", "15M") and self._cfg.require_htf_alignment_m15)
                or (tf in ("H4", "4H") and self._cfg.require_htf_alignment_h4)
            )
            ok, reason = check_htf_alignment(direction, htf_bias, required=require_htf)
            if not ok:
                return RiskDecision(allowed=False, reason=reason)

        ok, reason = check_no_opposite_position(
            direction, open_positions, symbol=symbol
        )
        if not ok:
            return RiskDecision(allowed=False, reason=reason)

        df = snapshot.get("ohlcv")
        if df is None or df.empty:
            return RiskDecision(allowed=False, reason="no data")

        regime = infer_regime_from_ohlcv(df)

        if _is_regime_kernel_signal(signal):
            return self._resolve_lot_for_signal(
                signal, snapshot, balance=balance, regime=regime
            )

        from tradingbot.config.price_action import get_price_action_config
        from tradingbot.adapters.timeframes import to_legacy

        pa_cfg = get_price_action_config(symbol, to_legacy(self._cfg.timeframe))
        ok, reason = check_market_filters(
            df,
            pa_cfg,
            strategy_mode=str(pa_cfg.get("GOLD_STRATEGY_MODE", "")),
        )
        if not ok:
            return RiskDecision(allowed=False, reason=reason)

        from tradingbot.services.meta_labeler import get_meta_labeler
        from tradingbot.domain.trade_features import capture_entry_features

        regime = infer_regime_from_ohlcv(df)
        hour = 12
        if current_time is not None and hasattr(current_time, "hour"):
            hour = int(current_time.hour)
        est_spread = (
            variable_spread_pips(self._cfg.spread_pips, hour)
            if self._cfg.variable_spread
            else self._cfg.spread_pips
        )

        meta_prob: float | None = None
        meta = get_meta_labeler()
        if self._cfg.use_meta_labeler and meta.should_gate(signal.timeframe, regime) and _is_pa_signal(signal):
            prob = meta.score(signal, snapshot, regime)
            meta_prob = prob
            base_th = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.52))
            threshold = meta.effective_threshold(signal.timeframe, regime, base_th)
            if prob < threshold:
                if hold_chain_enabled():
                    get_hold_chain().record(HoldStage.META)
                self._record_riskgate_block("meta-labeler rejected")
                return RiskDecision(allowed=False, reason=f"meta-labeler rejected (p={prob:.2f})")

        close = float(df["close"].iloc[-1])
        entry_feats = capture_entry_features(
            signal,
            snapshot,
            regime,
            spread_pips=est_spread,
            entry_price=close,
        )
        if signal.metadata is None:
            signal.metadata = {}
        signal.metadata["_entry_features"] = entry_feats
        signal.metadata["_regime"] = regime
        if meta_prob is not None:
            signal.metadata["_meta_prob"] = meta_prob

        return self._resolve_lot_for_signal(
            signal, snapshot, balance=balance, regime=regime
        )

    def on_trade_closed(self, pnl: float, cursor: int) -> None:
        if pnl < 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._cfg.max_consecutive_losses:
                self._pause_until_bar = cursor + self._cfg.cooldown_after_loss_bars
        else:
            self._consecutive_losses = 0

    @staticmethod
    def _as_datetime(ts: object | None) -> datetime | None:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts
        if hasattr(ts, "to_pydatetime"):
            return ts.to_pydatetime()  # type: ignore[union-attr]
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", ""))
            except ValueError:
                return None
        return None

    def _position_size(
        self,
        balance: float,
        price: float,
        sl: float | None,
        symbol: str,
        *,
        regime: str = "RANGING",
        risk_pct: float | None = None,
    ) -> float:
        from tradingbot.domain.risk_logic import regime_position_multiplier

        if not sl or sl <= 0 or price <= 0:
            return 0.0

        broker_symbol = resolve_broker_symbol(symbol, self._legacy_config)
        economics = resolve_backtest_economics(broker_symbol, self._legacy_config)
        if economics is None:
            return 0.0

        risk_fraction = risk_pct if risk_pct is not None else self._cfg.risk_per_trade
        lot, reason = lot_from_broker_economics(
            balance,
            risk_fraction,
            price,
            float(sl),
            economics,
            regime_multiplier=regime_position_multiplier(regime),
        )
        if lot is None:
            return 0.0
        return min(float(lot), self._cfg.max_lot)
