"""
گیت ریسک — پیاده‌سازی IRiskGate با فیلترهای live استاندارد + کنترل‌های بک‌تست.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd

from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.adapters.timeframes import to_legacy
from tradingbot.config.price_action import get_price_action_config
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain import risk_logic
from tradingbot.domain.market_filters import check_market_filters
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv, lot_from_stop_distance
from tradingbot.domain.live_gates import (
    check_friday_gate,
    check_htf_alignment,
    check_max_positions,
    check_news_gate,
    check_no_opposite_position,
    check_spread_gate,
    count_open_positions,
)
from tradingbot.domain.models import RiskDecision, TradingSignal
from tradingbot.domain.position_logic import contract_size, pip_size
from tradingbot.domain.session_logic import spread_pips_from_prices
from tradingbot.ml.research.phase22c.hold_chain import HoldStage, get_hold_chain, hold_chain_enabled
from tradingbot.ports.risk import IRiskGate
from tradingbot.services.live_risk_tracker import LiveRiskTracker

logger = logging.getLogger(__name__)

_tracker = LiveRiskTracker()


class AccountTier(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    STANDARD = "STANDARD"


@dataclass(frozen=True)
class ExecutionProfile:
    """Capital-adaptive execution eligibility — does not alter signal generation."""

    confidence_threshold: float | None
    max_positions_per_symbol: int | None
    require_h1_alignment: bool
    require_full_confluence: bool
    daily_loss_limit_multiplier: float
    cooldown_after_loss_multiplier: float
    risk_per_trade_override: float | None = None
    trading_style: str = "XAUUSD_STANDARD"
    max_hold_multiplier: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence_threshold": self.confidence_threshold,
            "max_positions_per_symbol": self.max_positions_per_symbol,
            "require_h1_alignment": self.require_h1_alignment,
            "require_full_confluence": self.require_full_confluence,
            "daily_loss_limit_multiplier": self.daily_loss_limit_multiplier,
            "cooldown_after_loss_multiplier": self.cooldown_after_loss_multiplier,
            "risk_per_trade_override": self.risk_per_trade_override,
            "trading_style": self.trading_style,
            "max_hold_multiplier": self.max_hold_multiplier,
        }


@dataclass(frozen=True)
class PositionManagementProfile:
    """XAUUSD open-position management — Phase 36A / 52A."""

    breakeven_enabled: bool = True
    partial_close_enabled: bool = True
    atr_trailing_enabled: bool = True
    time_exit_enabled: bool = True
    breakeven_trigger_r: float = 0.8
    partial_trigger_r: float = 1.2
    trailing_trigger_r: float = 1.4
    trailing_atr_multiplier: float = 1.4
    trailing_min_pips: float = 0.0
    trailing_requires_partial: bool = False
    stagnation_bars_limit: int = 36
    stagnation_min_profit_r: float = 0.3
    partial_fraction: float = 0.5


def detect_account_tier(equity: float) -> AccountTier:
    """Pure helper — no side effects."""
    if equity < 500:
        return AccountTier.MICRO
    if equity < 5000:
        return AccountTier.SMALL
    return AccountTier.STANDARD


def position_management_profile_for_tier(tier: AccountTier) -> PositionManagementProfile:
    """Tier-aware XAUUSD position management parameters."""
    if tier == AccountTier.MICRO:
        return PositionManagementProfile(
            trailing_atr_multiplier=0.9,
            stagnation_bars_limit=24,
        )
    if tier == AccountTier.SMALL:
        return PositionManagementProfile(
            trailing_atr_multiplier=1.1,
            stagnation_bars_limit=36,
        )
    return PositionManagementProfile(
        trailing_atr_multiplier=1.6,
        stagnation_bars_limit=36,
    )


def phase52a_position_management_profile() -> PositionManagementProfile:
    """Phase 52A — professional position management (all tiers)."""
    return PositionManagementProfile(
        breakeven_trigger_r=0.8,
        partial_trigger_r=1.0,
        trailing_trigger_r=1.0,
        trailing_atr_multiplier=0.8,
        trailing_min_pips=8.0,
        trailing_requires_partial=True,
        stagnation_bars_limit=12,
        stagnation_min_profit_r=0.2,
        partial_fraction=0.5,
    )


def resolve_position_management_profile(
    tier: AccountTier,
    *,
    phase52a: bool = False,
) -> PositionManagementProfile:
    if phase52a:
        return phase52a_position_management_profile()
    return position_management_profile_for_tier(tier)


def compute_min_lot_risk_usd(
    stop_distance_pips: float,
    min_lot: float,
    contract_size: float,
    pip_size: float,
) -> float:
    """USD risk if forced to trade at broker minimum lot."""
    stop_distance = stop_distance_pips * pip_size
    return float(min_lot * stop_distance * contract_size)


@dataclass(frozen=True)
class FeasibleRiskPlan:
    can_execute: bool
    effective_risk_pct: float
    target_risk_usd: float
    actual_risk_usd: float
    raw_lot: float
    final_lot: float
    adjusted: bool
    reason: str | None


def build_feasible_risk_plan(
    equity: float,
    requested_risk_pct: float,
    stop_distance_pips: float,
    min_lot: float,
    contract_size: float,
    pip_size: float,
) -> FeasibleRiskPlan:
    """Capital-adaptive lot/risk planner for MICRO min-lot economics."""
    target_risk_usd = round(float(equity) * float(requested_risk_pct), 4)
    stop_distance = stop_distance_pips * pip_size
    risk_per_unit = stop_distance * contract_size
    if risk_per_unit <= 0 or equity <= 0:
        return FeasibleRiskPlan(
            can_execute=False,
            effective_risk_pct=0.0,
            target_risk_usd=target_risk_usd,
            actual_risk_usd=0.0,
            raw_lot=0.0,
            final_lot=0.0,
            adjusted=False,
            reason="MICRO_INFEASIBLE_RISK",
        )

    raw_lot = target_risk_usd / risk_per_unit
    if raw_lot >= min_lot - 1e-9:
        actual = round(raw_lot * risk_per_unit, 4)
        return FeasibleRiskPlan(
            can_execute=True,
            effective_risk_pct=float(requested_risk_pct),
            target_risk_usd=target_risk_usd,
            actual_risk_usd=actual,
            raw_lot=round(raw_lot, 4),
            final_lot=round(raw_lot, 4),
            adjusted=False,
            reason=None,
        )

    actual_risk_usd = round(
        compute_min_lot_risk_usd(stop_distance_pips, min_lot, contract_size, pip_size),
        4,
    )
    effective_risk_pct = actual_risk_usd / float(equity)
    if effective_risk_pct <= 0.01:
        return FeasibleRiskPlan(
            can_execute=True,
            effective_risk_pct=round(effective_risk_pct, 6),
            target_risk_usd=target_risk_usd,
            actual_risk_usd=actual_risk_usd,
            raw_lot=round(raw_lot, 4),
            final_lot=float(min_lot),
            adjusted=True,
            reason="MICRO_FEASIBLE_EXECUTION",
        )

    return FeasibleRiskPlan(
        can_execute=False,
        effective_risk_pct=round(effective_risk_pct, 6),
        target_risk_usd=target_risk_usd,
        actual_risk_usd=actual_risk_usd,
        raw_lot=round(raw_lot, 4),
        final_lot=float(min_lot),
        adjusted=True,
        reason="MICRO_INFEASIBLE_RISK",
    )


MICRO_MAX_EFFECTIVE_RISK_PCT = 0.01
ABNORMAL_STOP_PIPS = 1000.0


def resolve_signal_entry_price(
    signal: TradingSignal,
    ohlcv: pd.DataFrame | None = None,
    *,
    broker_symbol: str = "",
) -> float:
    """Best-effort entry for stop-distance math — metadata, OHLCV close, then live tick."""
    entry = float(getattr(signal, "entry_price", None) or 0.0)
    if entry <= 0 and signal.metadata:
        entry = float(signal.metadata.get("entry", signal.metadata.get("price", 0.0)) or 0.0)
    if entry <= 0 and isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty:
        entry = float(ohlcv["close"].iloc[-1])
    if entry <= 0 and broker_symbol:
        try:
            import MetaTrader5 as mt5

            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is not None:
                if signal.direction.name == "BUY":
                    entry = float(tick.ask)
                elif signal.direction.name == "SELL":
                    entry = float(tick.bid)
        except Exception:
            pass
    return entry


def entry_and_sl_from_signal(
    signal: TradingSignal,
    ohlcv: pd.DataFrame | None = None,
    *,
    broker_symbol: str = "",
) -> tuple[float, float]:
    """Entry + SL from signal fields / metadata (shared live + backtest)."""
    entry = resolve_signal_entry_price(signal, ohlcv, broker_symbol=broker_symbol)
    sl = float(signal.stop_loss or 0.0)
    return entry, sl


def _log_stop_forensic(
    signal: TradingSignal,
    *,
    entry: float,
    stop_loss: float,
    take_profit: float | None,
    broker_symbol: str,
) -> None:
    """Phase 42B — temporary stop-distance forensic logging."""
    point = None
    digits = None
    tick_size = None
    tick_value = None
    from tradingbot.adapters.legacy_loader import load_legacy_config

    sym = broker_symbol
    if not sym:
        sym = resolve_broker_symbol(signal.symbol, load_legacy_config())
    try:
        import MetaTrader5 as mt5

        if not sym:
            sym = resolve_broker_symbol(signal.symbol, load_legacy_config())
        info = mt5.symbol_info(sym)
        if info is not None:
            point = float(info.point)
            digits = int(info.digits)
            tick_size = float(info.trade_tick_size)
            tick_value = float(info.trade_tick_value)
    except Exception:
        pass
    logger.warning(
        "STOP FORENSIC | symbol=%s entry=%s sl=%s tp=%s point=%s digits=%s "
        "tick_size=%s tick_value=%s raw_diff=%s",
        sym,
        entry,
        stop_loss,
        take_profit,
        point,
        digits,
        tick_size,
        tick_value,
        abs(entry - stop_loss) if stop_loss > 0 else None,
    )


def adapt_xauusd_stop_for_tier_signal(
    signal: TradingSignal,
    tier: AccountTier,
    ohlcv: pd.DataFrame | None,
) -> dict[str, float]:
    """
    Adapt XAUUSD SL/TP to tier profile (live + backtest parity).
    Mutates signal.stop_loss / signal.take_profit. Returns stop diagnostics.
    """
    symbol = (signal.symbol or "").upper()
    out = {
        "stop_pips": 0.0,
        "compressed_stop_pips": 0.0,
        "stop_pips_after": 0.0,
    }
    if not symbol.startswith("XAU"):
        return out

    from tradingbot.domain.signal_helpers import (
        _atr,
        compress_micro_stop_pips,
        confluence_sl_mult_for_tier,
        confluence_tp_rr_for_tier,
    )

    entry, sl = entry_and_sl_from_signal(signal, ohlcv)
    if entry <= 0:
        return out

    ps = pip_size(signal.symbol)
    out["stop_pips"] = round(abs(entry - sl) / ps, 2) if sl > 0 and ps > 0 else 0.0

    sl_mult = confluence_sl_mult_for_tier(tier.value)
    tp_rr = confluence_tp_rr_for_tier(tier.value)
    direction = 1 if signal.direction.name == "BUY" else -1 if signal.direction.name == "SELL" else 0
    if direction == 0:
        return out

    if isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty:
        atr = _atr(ohlcv, symbol=signal.symbol)
    elif sl > 0:
        atr = abs(entry - sl) / sl_mult
    else:
        return out

    if direction > 0:
        new_sl = entry - atr * sl_mult
        new_tp = entry + (entry - new_sl) * tp_rr
    else:
        new_sl = entry + atr * sl_mult
        new_tp = entry - (new_sl - entry) * tp_rr

    compressed_stop_pips = out["stop_pips"]
    if tier == AccountTier.MICRO:
        stop_pips = abs(entry - new_sl) / ps if ps > 0 else 0.0
        meta = signal.metadata or {}
        atr_pct_raw = meta.get("atr_pct")
        atr_pct = float(atr_pct_raw) if atr_pct_raw is not None else None
        compressed_stop_pips = compress_micro_stop_pips(stop_pips, atr_pct)
        out["compressed_stop_pips"] = round(compressed_stop_pips, 2)
        if compressed_stop_pips + 0.01 < stop_pips:
            from tradingbot.services.rejection_events import log_rejection_event

            log_rejection_event(
                stage="RISKGATE",
                reason=f"MICRO_STOP_COMPRESSED {stop_pips:.1f}p->{compressed_stop_pips:.1f}p",
                symbol=signal.symbol,
                direction=signal.direction.name,
                context={
                    "stop_pips_before": round(stop_pips, 2),
                    "stop_pips_after": round(compressed_stop_pips, 2),
                    "atr_pct": atr_pct,
                },
            )
            logger.info(
                "[RiskGate] MICRO stop compressed | %sp -> %sp",
                round(stop_pips, 1),
                round(compressed_stop_pips, 1),
            )
            if direction > 0:
                new_sl = entry - compressed_stop_pips * ps
            else:
                new_sl = entry + compressed_stop_pips * ps
            tp_rr = 1.2
            if direction > 0:
                new_tp = entry + (entry - new_sl) * tp_rr
            else:
                new_tp = entry - (new_sl - entry) * tp_rr

    old_pips = round(abs(entry - sl) / ps, 1) if sl > 0 else None
    new_pips = round(abs(entry - new_sl) / ps, 1)
    out["stop_pips_after"] = float(new_pips)

    signal.stop_loss = float(new_sl)
    signal.take_profit = float(new_tp)
    if signal.metadata is None:
        signal.metadata = {}
    signal.metadata["capital_adaptive_sl_mult"] = sl_mult
    signal.metadata["capital_adaptive_tp_rr"] = tp_rr
    signal.metadata["account_tier"] = tier.value
    if old_pips is not None and old_pips > new_pips + 0.05:
        signal.metadata["xauusd_stop_adapted"] = True
        signal.metadata["xauusd_stop_pips_before"] = old_pips
        signal.metadata["xauusd_stop_pips_after"] = new_pips
    return out


def classify_micro_rejection_reason(
    plan: FeasibleRiskPlan,
    *,
    stop_pips_before: float,
    stop_pips_after: float,
) -> str:
    """Map planner output to explicit MICRO rejection codes."""
    if plan.can_execute:
        return ""
    if plan.effective_risk_pct > MICRO_MAX_EFFECTIVE_RISK_PCT:
        if stop_pips_before > stop_pips_after + 0.05:
            return "MICRO_STOP_TOO_WIDE"
        if plan.raw_lot < 0.01 - 1e-9:
            return "MIN_LOT_EXCEEDS_MICRO_CAP"
        return "MICRO_EFFECTIVE_RISK_CAP_EXCEEDED"
    return plan.reason or "MICRO_INFEASIBLE_RISK"


def evaluate_micro_feasible_risk(
    signal: TradingSignal,
    equity: float,
    *,
    tier: AccountTier,
    requested_risk_pct: float,
    min_lot: float,
    max_lot: float,
    ohlcv: pd.DataFrame | None = None,
    adapt_stop: bool = True,
    log_rejections: bool = True,
    broker_symbol: str = "",
) -> tuple[RiskDecision | None, float, dict[str, Any]]:
    """
    Shared MICRO feasibility gate for live RiskGate and BacktestRiskGate.
    Returns (reject_decision|None, final_lot, diagnostics).
    """
    stop_diag: dict[str, float] = {
        "stop_pips": 0.0,
        "compressed_stop_pips": 0.0,
        "stop_pips_after": 0.0,
    }
    if adapt_stop:
        stop_diag = adapt_xauusd_stop_for_tier_signal(signal, tier, ohlcv)

    entry, sl = entry_and_sl_from_signal(signal, ohlcv, broker_symbol=broker_symbol)
    if entry > 0:
        if signal.metadata is None:
            signal.metadata = {}
        signal.metadata.setdefault("entry", entry)
        signal.metadata.setdefault("price", entry)

    tp = float(signal.take_profit or 0.0)
    _log_stop_forensic(
        signal,
        entry=entry,
        stop_loss=sl,
        take_profit=tp if tp > 0 else None,
        broker_symbol=broker_symbol,
    )

    ps = pip_size(signal.symbol)
    cs = contract_size(signal.symbol)
    stop_distance_pips = abs(entry - sl) / ps if ps > 0 and sl > 0 and entry > 0 else 0.0

    direction = signal.direction.name
    wrong_side = (
        entry > 0
        and sl > 0
        and ((direction == "BUY" and sl >= entry) or (direction == "SELL" and sl <= entry))
    )
    if entry <= 0 or wrong_side or stop_distance_pips > ABNORMAL_STOP_PIPS:
        logger.error(
            "ABNORMAL STOP DISTANCE | entry=%s sl=%s distance=%s wrong_side=%s",
            entry,
            sl,
            stop_distance_pips,
            wrong_side,
        )
        reason = (
            f"ABNORMAL_STOP_DISTANCE entry={entry:.5f} sl={sl:.5f} "
            f"distance_pips={stop_distance_pips:.2f}"
        )
        if log_rejections:
            from tradingbot.services.rejection_events import log_rejection_event

            log_rejection_event(
                stage="RISKGATE",
                reason=reason,
                symbol=signal.symbol,
                direction=direction,
                context={
                    "entry": entry,
                    "stop_loss": sl,
                    "stop_distance_pips": round(stop_distance_pips, 2),
                    "wrong_side": wrong_side,
                },
            )
        return RiskDecision(allowed=False, reason=reason), 0.0, {
            "stop_pips": round(stop_distance_pips, 2),
            "rejection_reason": "ABNORMAL_STOP_DISTANCE",
            "feasible_execution": False,
        }

    plan = build_feasible_risk_plan(
        equity,
        requested_risk_pct,
        stop_distance_pips,
        min_lot,
        cs,
        ps,
    )

    diag: dict[str, Any] = {
        "stop_pips": stop_diag.get("stop_pips") or round(stop_distance_pips, 2),
        "compressed_stop_pips": stop_diag.get("compressed_stop_pips")
        or round(stop_distance_pips, 2),
        "stop_pips_after": stop_diag.get("stop_pips_after") or round(stop_distance_pips, 2),
        "requested_risk_pct": round(float(requested_risk_pct) * 100, 4),
        "effective_risk_pct": round(float(plan.effective_risk_pct) * 100, 4),
        "effective_risk_decimal": float(plan.effective_risk_pct),
        "raw_lot": plan.raw_lot,
        "final_lot": plan.final_lot,
        "feasible_execution": plan.can_execute,
        "adjusted": plan.adjusted,
        "rejection_reason": "",
        "actual_risk_usd": plan.actual_risk_usd,
        "target_risk_usd": plan.target_risk_usd,
    }

    if plan.can_execute:
        final_lot = max(min_lot, min(plan.final_lot, max_lot))
        diag["final_lot"] = final_lot
        return None, final_lot, diag

    rejection = classify_micro_rejection_reason(
        plan,
        stop_pips_before=float(diag["stop_pips"]),
        stop_pips_after=float(diag["stop_pips_after"]),
    )
    diag["rejection_reason"] = rejection
    reason = (
        f"{rejection} "
        f"tier={tier.value} "
        f"target_risk_usd={plan.target_risk_usd:.2f} "
        f"actual_risk_usd={plan.actual_risk_usd:.2f} "
        f"effective_risk_pct={plan.effective_risk_pct:.4f} "
        f"stop_distance_pips={stop_distance_pips:.2f} "
        f"min_lot={min_lot:.2f} "
        f"raw_lot={plan.raw_lot:.4f}"
    )
    if log_rejections:
        from tradingbot.services.rejection_events import log_rejection_event

        logger.warning("[RiskGate] %s", reason)
        log_rejection_event(
            stage="RISKGATE",
            reason=reason,
            symbol=signal.symbol,
            direction=signal.direction.name,
            context={
                "rejection_code": rejection,
                "effective_risk_pct": plan.effective_risk_pct,
                "actual_risk_usd": plan.actual_risk_usd,
                "stop_distance_pips": round(stop_distance_pips, 2),
                "stop_pips_before": diag["stop_pips"],
                "compressed_stop_pips": diag["compressed_stop_pips"],
            },
        )
    suffix = f" ({broker_symbol})" if broker_symbol else ""
    return RiskDecision(allowed=False, reason=f"{reason}{suffix}"), plan.final_lot, diag


def execution_profile_for_tier(tier: AccountTier) -> ExecutionProfile:
    """Derive execution eligibility profile from account tier."""
    if tier == AccountTier.MICRO:
        return ExecutionProfile(
            confidence_threshold=0.55,
            max_positions_per_symbol=1,
            require_h1_alignment=False,
            require_full_confluence=True,
            daily_loss_limit_multiplier=0.5,
            cooldown_after_loss_multiplier=2.0,
            risk_per_trade_override=0.0025,
            trading_style="XAUUSD_SCALP",
            max_hold_multiplier=0.5,
        )
    if tier == AccountTier.SMALL:
        return ExecutionProfile(
            confidence_threshold=0.60,
            max_positions_per_symbol=1,
            require_h1_alignment=True,
            require_full_confluence=True,
            daily_loss_limit_multiplier=1.0,
            cooldown_after_loss_multiplier=1.0,
            risk_per_trade_override=0.005,
            trading_style="XAUUSD_INTRADAY",
            max_hold_multiplier=1.0,
        )
    return ExecutionProfile(
        confidence_threshold=None,
        max_positions_per_symbol=None,
        require_h1_alignment=False,
        require_full_confluence=False,
        daily_loss_limit_multiplier=1.0,
        cooldown_after_loss_multiplier=1.0,
        trading_style="XAUUSD_STANDARD",
        max_hold_multiplier=1.0,
    )


def capital_adaptive_snapshot(
    equity: float,
    *,
    config_risk_per_trade: float = 0.005,
    stop_distance_pips: float = 18.0,
    min_lot: float = 0.01,
) -> dict[str, Any]:
    """Runtime-truth payload for capital-adaptive state."""
    from tradingbot.domain.position_logic import contract_size as cs_fn, pip_size as ps_fn
    from tradingbot.domain.signal_helpers import confluence_sl_mult_for_tier, confluence_tp_rr_for_tier
    from tradingbot.services.exit_policy import DEFAULT_MAX_HOLD_BARS
    from tradingbot.config.live import PRIMARY_SYMBOL

    tier = detect_account_tier(equity)
    profile = execution_profile_for_tier(tier)
    pm = position_management_profile_for_tier(tier)
    requested_risk = (
        profile.risk_per_trade_override
        if profile.risk_per_trade_override is not None
        else config_risk_per_trade
    )
    sl_mult = confluence_sl_mult_for_tier(tier.value)
    sym_cs = cs_fn(PRIMARY_SYMBOL)
    sym_ps = ps_fn(PRIMARY_SYMBOL)
    plan = build_feasible_risk_plan(
        equity,
        requested_risk,
        stop_distance_pips,
        min_lot,
        sym_cs,
        sym_ps,
    )
    effective_risk = plan.effective_risk_pct if plan.can_execute else requested_risk
    return {
        "capital_adaptive_mode": profile.trading_style,
        "account_tier": tier.value,
        "trading_style": profile.trading_style,
        "capital_adaptive_enabled": True,
        "account_equity": round(float(equity), 2),
        "effective_sl_multiplier": sl_mult,
        "effective_tp_rr": confluence_tp_rr_for_tier(tier.value),
        "effective_risk": effective_risk,
        "effective_risk_per_trade": effective_risk,
        "effective_confluence_sl_mult": sl_mult,
        "effective_max_hold_bars": int(DEFAULT_MAX_HOLD_BARS * profile.max_hold_multiplier),
        "breakeven_enabled": pm.breakeven_enabled,
        "partial_close_enabled": pm.partial_close_enabled,
        "atr_trailing_enabled": pm.atr_trailing_enabled,
        "time_exit_enabled": pm.time_exit_enabled,
        "trailing_atr_multiplier": pm.trailing_atr_multiplier,
        "stagnation_bars_limit": pm.stagnation_bars_limit,
        "requested_risk_pct": round(float(requested_risk), 6),
        "effective_risk_pct": round(float(plan.effective_risk_pct), 6),
        "micro_risk_adjusted": bool(plan.adjusted),
        "feasible_execution": bool(plan.can_execute),
        "actual_risk_at_min_lot_usd": round(float(plan.actual_risk_usd), 4),
        "execution_profile": {
            "confidence_threshold": profile.confidence_threshold,
            "max_positions_per_symbol": profile.max_positions_per_symbol,
            "require_h1_alignment": profile.require_h1_alignment,
            "require_full_confluence": profile.require_full_confluence,
            "daily_loss_limit_multiplier": profile.daily_loss_limit_multiplier,
            "cooldown_after_loss_multiplier": profile.cooldown_after_loss_multiplier,
            "risk_per_trade_override": profile.risk_per_trade_override,
            "trading_style": profile.trading_style,
            "max_hold_multiplier": profile.max_hold_multiplier,
        },
    }


def _stamp_pa_production_trade_metadata(
    signal: TradingSignal,
    *,
    meta_prob: float | None,
    meta_decision: str | None,
    effective_risk_decimal: float,
    ohlcv: pd.DataFrame | None,
) -> None:
    """Phase 50A — required audit fields on every approved PA trade."""
    if signal.metadata is None:
        signal.metadata = {}
    entry, sl = entry_and_sl_from_signal(signal, ohlcv)
    ps = pip_size(signal.symbol)
    stop_pips = abs(entry - sl) / ps if sl > 0 and entry > 0 and ps > 0 else 0.0
    tp = float(signal.take_profit or 0.0)
    rr_target = 0.0
    if tp > 0 and sl > 0 and entry > 0:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr_target = reward / risk if risk > 0 else 0.0
    signal.metadata.update({
        "selected_engine": signal.metadata.get("selected_engine")
        or signal.metadata.get("router_engine", "PA"),
        "meta_probability": round(float(meta_prob), 4) if meta_prob is not None else None,
        "meta_decision": meta_decision,
        "stop_pips": round(stop_pips, 2),
        "effective_risk_pct": round(float(effective_risk_decimal) * 100, 4),
        "rr_target": round(rr_target, 3),
    })


def _is_vol_regime_signal(signal: TradingSignal) -> bool:
    name = (signal.strategy_name or "").upper()
    return name in ("VOL_REGIME", "ADAPTIVE_REGIME")


def apply_pa_meta_decision(
    *,
    prob: float,
    threshold: float,
    gating: bool,
    observer_mode: bool,
) -> tuple[bool, bool, str]:
    """Return (should_reject_trade, would_reject, decision_label).

    Observer mode never rejects. ``would_reject`` is the counterfactual of
    ``meta_score < effective_threshold``. When observer is off, the live
    reject still requires ``gating`` so skip-regimes stay skip-regimes.
    """
    would_reject = float(prob) < float(threshold)
    if observer_mode:
        label = "observer_would_reject" if would_reject else "approved"
        return False, would_reject, label
    if gating and would_reject:
        return True, True, "rejected"
    return False, would_reject, "approved"


def meta_observer_mode_enabled(config: dict[str, Any] | None = None) -> bool:
    if isinstance(config, dict) and config.get("META_OBSERVER_MODE") is not None:
        return bool(config.get("META_OBSERVER_MODE"))
    try:
        from tradingbot.config.live import META_OBSERVER_MODE, get_live_config

        return bool(get_live_config().get("META_OBSERVER_MODE", META_OBSERVER_MODE))
    except Exception:
        return False


def _stamp_meta_observer_fields(
    signal: TradingSignal,
    *,
    meta_score: float,
    meta_threshold: float,
    meta_would_reject: bool,
    meta_observer_mode: bool,
) -> None:
    if signal.metadata is None:
        signal.metadata = {}
    signal.metadata["meta_score"] = round(float(meta_score), 4)
    signal.metadata["meta_threshold"] = round(float(meta_threshold), 4)
    signal.metadata["meta_would_reject"] = bool(meta_would_reject)
    signal.metadata["meta_observer_mode"] = bool(meta_observer_mode)


def _is_pa_signal(signal: TradingSignal) -> bool:
    """True only for legacy Price Action — Adaptive/VOL/ML bypass meta (Phase 46B)."""
    name = (signal.strategy_name or "").lower()
    if name in ("vol_regime", "adaptive_regime"):
        return False
    meta = signal.metadata or {}
    engine = str(meta.get("engine_name", meta.get("engine_id", meta.get("sub_strategy", "")))).lower()
    if engine in ("vol_regime", "adaptive_regime", "ml_kernel"):
        return False
    return name in ("priceaction", "price_action", "pa") or name.startswith("priceaction")


@dataclass
class AccountState:
    balance: float = 10_000.0
    equity: float = 10_000.0
    positions: list[Any] = field(default_factory=list)

    def get_leverage(self) -> float:
        if self.balance <= 0:
            return 0.0
        total_exposure = sum(
            abs(getattr(p, "volume", 0.0) * getattr(p, "entry_price", 0.0))
            for p in self.positions
        )
        return total_exposure / self.balance


def create_risk_gate(config: dict[str, Any] | None = None) -> "RiskGate":
    cfg = config or {}
    balance = float(cfg.get("initial_balance", cfg.get("INITIAL_BALANCE", 10_000)))
    equity = balance
    try:
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is not None:
            balance = float(info.balance)
            equity = float(info.equity)
            from tradingbot.services.runtime_truth import refresh_live_equity_from_mt5

            refresh_live_equity_from_mt5(log_freeze=False)
    except Exception:
        pass
    account = AccountState(balance=balance, equity=equity)
    gate = RiskGate(account, cfg)
    if equity > 0:
        gate._initial_balance = balance
    return gate


class RiskGate(IRiskGate):
    def __init__(self, account: AccountState, config: dict[str, Any] | None = None) -> None:
        self._account = account
        self._config = config or {}
        self._limits = risk_logic.RiskLimits.from_config(self._config)
        pa = self._config.get("PRICE_ACTION", {})
        self._default_lot = float(
            self._config.get("DEFAULT_LOT_SIZE", self._config.get("default_lot_size", 0.01))
        )
        self._min_lot = float(self._config.get("MIN_LOT_SIZE", 0.01))
        self._max_lot = float(self._config.get("MAX_LOT_SIZE", 1.0))
        self._lot_step = float(self._config.get("LOT_STEP", 0.01))
        self._min_lot_over_risk_multiplier = 2.0
        self._risk_per_trade = float(
            self._config.get("RISK_PER_TRADE", self._config.get("risk_per_trade", risk_logic.DEFAULT_RISK_PER_TRADE))
        )
        self._initial_balance = float(
            self._config.get("INITIAL_BALANCE", self._config.get("initial_balance", 10_000))
        )
        self._max_daily_loss_pct = float(
            self._config.get("MAX_DAILY_RISK", self._config.get("max_daily_loss", 0.04))
        )
        self._regime = "RANGING"
        self._max_positions_total = int(
            self._config.get("MAX_OPEN_POSITIONS_TOTAL", pa.get("MAX_OPEN_POSITIONS_TOTAL", 2))
        )
        self._max_positions_symbol = int(
            self._config.get("MAX_OPEN_POSITIONS_PER_SYMBOL", pa.get("MAX_OPEN_POSITIONS_PER_SYMBOL", 2))
        )
        self._max_spread_pips = float(
            pa.get("MAX_SPREAD_PIPS", self._config.get("MAX_SPREAD_PIPS", 5.0))
        )
        # Gold live tick spread on demo/ECN often 4–12 pips; 15 avoids false blocks.
        if str(self._config.get("SYMBOLS", [PRIMARY_SYMBOL])[0]).upper().startswith("XAU"):
            self._max_spread_pips = max(self._max_spread_pips, 15.0)
        self._use_news_filter = bool(pa.get("USE_NEWS_FILTER", self._config.get("USE_NEWS_FILTER", True)))
        self._news_minutes = int(pa.get("NEWS_BLACKOUT_MINUTES", 30))
        self._friday_no_entry = int(pa.get("FRIDAY_NO_ENTRY_AFTER_HOUR", 17))
        self._tracker = _tracker
        live = self._config.get("VOL_REGIME_ENABLED")
        self._vol_regime_live = bool(live if live is not None else self._config.get("vol_regime_enabled"))
        self._vol_regime_max_concurrent = int(self._config.get("VOL_REGIME_MAX_CONCURRENT", 1))
        self._vol_regime_cooldown_bars = int(self._config.get("VOL_REGIME_COOLDOWN_BARS", 6))
        self._vol_regime_max_trades_day = int(
            self._config.get("VOL_REGIME_MAX_TRADES_PER_DAY", self._config.get("MAX_TRADES_PER_DAY", 5))
        )
        self._capital_adaptive_enabled = True
        self._eval_risk_per_trade = self._risk_per_trade

    def _effective_risk_per_trade(self, tier: AccountTier, profile: ExecutionProfile) -> float:
        if profile.risk_per_trade_override is not None:
            return float(profile.risk_per_trade_override)
        return self._risk_per_trade

    def _tier_and_profile(self) -> tuple[AccountTier, ExecutionProfile]:
        tier = detect_account_tier(float(self._account.equity))
        return tier, execution_profile_for_tier(tier)

    def _capital_adaptive_gates(
        self,
        signal: TradingSignal,
        profile: ExecutionProfile,
        snapshot: dict,
    ) -> tuple[bool, str]:
        """Execution eligibility only — signal generation is unchanged."""
        if profile.confidence_threshold is not None:
            if float(signal.confidence) < profile.confidence_threshold:
                return False, (
                    f"capital-adaptive confidence "
                    f"({signal.confidence:.2f}<{profile.confidence_threshold:.2f})"
                )

        if profile.require_full_confluence and _is_vol_regime_signal(signal):
            meta = signal.metadata or {}
            sub = str(meta.get("sub_strategy", meta.get("engine_id", ""))).upper()
            if sub != "CONFLUENCE":
                return False, f"capital-adaptive requires full confluence (sub_strategy={sub or 'unknown'})"

        if profile.require_h1_alignment:
            direction = 1 if signal.direction.name == "BUY" else -1 if signal.direction.name == "SELL" else 0
            htf_bias = int(snapshot.get("htf_bias", 0) or 0)
            ok, reason = check_htf_alignment(direction, htf_bias, required=True)
            if not ok:
                return False, f"capital-adaptive h1 alignment ({reason})"

        return True, "ok"

    @property
    def account(self) -> AccountState:
        return self._account

    def portfolio_snapshot(self) -> dict[str, Any]:
        self._sync_mt5_account()
        return {
            "balance": self._account.balance,
            "equity": self._account.equity,
            "open_positions": list(self._account.positions),
            "correlation_data": {},
        }

    def evaluate(self, signal: TradingSignal, portfolio_snapshot: dict) -> RiskDecision:
        from tradingbot.services.runtime_truth import entries_frozen

        if entries_frozen():
            broker_symbol = resolve_broker_symbol(signal.symbol, self._config)
            return RiskDecision(
                allowed=False,
                reason=f"MT5 equity unavailable — new entries frozen ({broker_symbol})",
            )

        broker_symbol = resolve_broker_symbol(signal.symbol, self._config)
        self._sync_mt5_account()
        positions = list(self._account.positions) or list(portfolio_snapshot.get("open_positions", []))

        df = portfolio_snapshot.get("ohlcv")
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            self._regime = infer_regime_from_ohlcv(df)

        self._tracker.sync_from_mt5(self._account.equity, self._config)
        self._maybe_activate_loss_streak_cap(signal)

        tier, profile = self._tier_and_profile()
        self._eval_risk_per_trade = self._effective_risk_per_trade(tier, profile)
        ok, reason = self._capital_adaptive_gates(signal, profile, portfolio_snapshot)
        if not ok:
            return RiskDecision(allowed=False, reason=f"{reason} ({broker_symbol})")

        ok, reason = self._live_gates(signal, broker_symbol, positions, portfolio_snapshot, profile)
        if not ok:
            return RiskDecision(allowed=False, reason=f"{reason} ({broker_symbol})")

        if _is_vol_regime_signal(signal):
            max_trades = self._vol_regime_max_trades_day
            cooldown_bars = self._vol_regime_cooldown_bars
        else:
            pa_tf = get_price_action_config(signal.symbol, to_legacy(signal.timeframe))
            max_trades = int(pa_tf.get("MAX_TRADES_PER_DAY", self._config.get("MAX_TRADES_PER_DAY", 0)))
            from tradingbot.config.price_action import PA_COOLDOWN_BARS

            cooldown_bars = int(pa_tf.get("COOLDOWN_BARS", PA_COOLDOWN_BARS))
        cooldown_bars = int(cooldown_bars * profile.cooldown_after_loss_multiplier)

        ok, reason = self._tracker.check_entry_allowed(
            timeframe=signal.timeframe,
            max_trades_per_day=max_trades,
            cooldown_bars=cooldown_bars,
            equity=self._account.equity,
            initial_balance=self._account.balance or self._initial_balance,
            max_daily_loss_pct=self._max_daily_loss_pct * profile.daily_loss_limit_multiplier,
            config=self._config,
        )
        if not ok:
            return RiskDecision(allowed=False, reason=f"{reason} ({broker_symbol})")

        state = self._tracker.to_risk_state(leverage=self._account.get_leverage())
        allowed, reason = risk_logic.can_trade(state, self._limits)
        if not allowed:
            return RiskDecision(allowed=False, reason=f"{reason} ({broker_symbol})")

        from tradingbot.services.meta_labeler import get_meta_labeler
        from tradingbot.services.meta_decision_log import log_meta_decision, log_meta_observer_event
        from tradingbot.domain.trade_features import capture_entry_features

        meta = get_meta_labeler()
        meta_prob: float | None = None
        meta_decision: str | None = None
        spread_pips = self._live_spread_pips(broker_symbol, signal.symbol)

        if _is_pa_signal(signal):
            pa_tf = get_price_action_config(signal.symbol, to_legacy(signal.timeframe))
            base_th = float(pa_tf.get("META_LABEL_THRESHOLD", 0.40))
            threshold = meta.effective_threshold(signal.timeframe, self._regime, base_th)
            prob = meta.score(
                signal,
                portfolio_snapshot,
                self._regime,
                spread_pips=spread_pips,
            )
            meta_prob = prob
            feats_preview = capture_entry_features(
                signal,
                portfolio_snapshot,
                self._regime,
                spread_pips=spread_pips,
            )
            gating = meta.should_gate(signal.timeframe, self._regime)
            observer = meta_observer_mode_enabled(self._config)
            should_reject, would_reject, decision_label = apply_pa_meta_decision(
                prob=prob,
                threshold=threshold,
                gating=gating,
                observer_mode=observer,
            )
            _stamp_meta_observer_fields(
                signal,
                meta_score=prob,
                meta_threshold=threshold,
                meta_would_reject=would_reject,
                meta_observer_mode=observer,
            )
            if observer:
                observer_reason = (
                    "meta observer would reject"
                    if would_reject
                    else ("meta approved" if gating else "meta scored (gate off)")
                )
            else:
                observer_reason = "meta rejected" if should_reject else (
                    "meta approved" if gating else "meta scored (gate off)"
                )
            try:
                log_meta_observer_event(
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    meta_score=prob,
                    meta_threshold=threshold,
                    meta_would_reject=would_reject,
                    meta_observer_mode=observer,
                    signal_direction=signal.direction.name,
                    gating=gating,
                    rejected=should_reject,
                    reason=observer_reason,
                )
            except Exception:
                logger.debug("meta observer event log failed", exc_info=True)
            if should_reject:
                meta_decision = "rejected"
                if hold_chain_enabled():
                    get_hold_chain().record(HoldStage.META)
                try:
                    from tradingbot.services.meta_decision_log import log_meta_false_negative_candidate

                    sig_meta = signal.metadata or {}
                    ohlcv = portfolio_snapshot.get("ohlcv")
                    bar_ts = None
                    if isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty:
                        bar_ts = ohlcv.index[-1]
                    ts_raw = bar_ts or getattr(signal, "created_at", None)
                    if hasattr(ts_raw, "isoformat"):
                        ts_s = ts_raw.isoformat()
                    else:
                        ts_s = str(ts_raw or "")
                    entry = float(
                        sig_meta.get("entry")
                        or sig_meta.get("price")
                        or (float(ohlcv["close"].iloc[-1]) if isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty else 0.0)
                    )
                    log_meta_false_negative_candidate(
                        timestamp=ts_s,
                        symbol=broker_symbol,
                        direction=signal.direction.name,
                        meta_score=prob,
                        threshold=threshold,
                        features=feats_preview,
                        entry=entry,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        timeframe=signal.timeframe,
                    )
                except Exception:
                    logger.debug("meta false-negative candidate log failed", exc_info=True)
                log_meta_decision(
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    allowed=False,
                    meta_prob=prob,
                    threshold=threshold,
                    reason="meta rejected",
                    features=feats_preview,
                    signal_direction=signal.direction.name,
                )
                return RiskDecision(
                    allowed=False,
                    reason=f"meta-labeler rejected (p={prob:.2f}<{threshold:.2f})",
                )
            meta_decision = decision_label
            log_meta_decision(
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                allowed=True,
                meta_prob=prob,
                threshold=threshold,
                reason=observer_reason,
                features=feats_preview,
                signal_direction=signal.direction.name,
            )

        if signal.metadata is None:
            signal.metadata = {}
        signal.metadata["_entry_features"] = capture_entry_features(
            signal,
            portfolio_snapshot,
            self._regime,
            spread_pips=spread_pips,
        )
        signal.metadata["_regime"] = self._regime
        if meta_prob is not None:
            signal.metadata["_meta_prob"] = meta_prob

        self._adapt_xauusd_stop_for_tier(signal, tier, portfolio_snapshot)

        lot = self._compute_lot(signal, portfolio_snapshot, broker_symbol)
        if tier == AccountTier.MICRO:
            micro_decision, lot = self._apply_micro_feasible_plan(
                signal, lot, tier, broker_symbol, portfolio_snapshot
            )
            if micro_decision is not None:
                return micro_decision
        else:
            reject = self._reject_min_lot_over_risk(signal, lot, tier)
            if reject is not None:
                return reject
        lot = max(self._min_lot, min(lot, self._max_lot))
        try:
            from tradingbot.services.phase47c_forward_tracker import is_phase47c_enabled, log_phase47c_event

            if is_phase47c_enabled():
                log_phase47c_event(
                    "riskgate_approved",
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    direction=signal.direction.name,
                    lot=round(lot, 4),
                    effective_risk_pct=round(float(self._eval_risk_per_trade) * 100, 4),
                )
        except Exception:
            pass
        ohlcv_snap = portfolio_snapshot.get("ohlcv")
        ohlcv_df = ohlcv_snap if isinstance(ohlcv_snap, pd.DataFrame) else None
        _stamp_pa_production_trade_metadata(
            signal,
            meta_prob=meta_prob,
            meta_decision=meta_decision,
            effective_risk_decimal=float(self._eval_risk_per_trade),
            ohlcv=ohlcv_df,
        )
        return RiskDecision(allowed=True, reason="approved", adjusted_lot=lot)

    @staticmethod
    def _is_trend_regime_for_signal(signal: TradingSignal, inferred_regime: str) -> bool:
        meta = signal.metadata or {}
        adaptive_regime = str(meta.get("regime", "") or "").upper()
        if adaptive_regime == "TREND":
            return True
        inferred = (inferred_regime or "").upper()
        return inferred in ("TREND", "STRONG_TREND_UP", "STRONG_TREND_DOWN")

    def _maybe_activate_loss_streak_cap(self, signal: TradingSignal) -> None:
        """Cap max concurrent positions after 5-loss streak in TREND — no signal block."""
        if not _is_vol_regime_signal(signal):
            return
        if self._tracker.consecutive_losses < 5:
            return
        if not self._is_trend_regime_for_signal(signal, self._regime):
            return
        self._tracker.activate_loss_streak_position_cap(m5_bars=12)

    def _live_gates(
        self,
        signal: TradingSignal,
        broker_symbol: str,
        positions: list[Any],
        snapshot: dict,
        profile: ExecutionProfile | None = None,
    ) -> tuple[bool, str]:
        open_total = count_open_positions(positions)
        open_sym = count_open_positions(positions, symbol=signal.symbol)
        max_total = self._max_positions_total
        max_per_symbol = self._max_positions_symbol
        if profile is not None and profile.max_positions_per_symbol is not None:
            max_per_symbol = profile.max_positions_per_symbol
        if self._tracker.loss_streak_position_cap_active():
            max_per_symbol = min(max_per_symbol, 1)
        if _is_vol_regime_signal(signal):
            max_total = min(max_total, self._vol_regime_max_concurrent)
            max_per_symbol = min(max_per_symbol, self._vol_regime_max_concurrent)

        ok, reason = check_max_positions(
            open_total,
            open_sym,
            max_total=max_total,
            max_per_symbol=max_per_symbol,
        )
        if not ok:
            return False, reason

        ts = self._as_datetime(snapshot.get("current_time")) or datetime.now(timezone.utc)
        ok, reason = check_news_gate(ts, enabled=self._use_news_filter, minutes=self._news_minutes)
        if not ok:
            return False, reason

        ok, reason = check_friday_gate(ts, no_entry_after_hour=self._friday_no_entry)
        if not ok:
            return False, reason

        spread_pips = self._live_spread_pips(broker_symbol, signal.symbol)
        ok, reason = check_spread_gate(spread_pips, self._max_spread_pips)
        if not ok:
            return False, reason

        direction = 1 if signal.direction.name == "BUY" else -1 if signal.direction.name == "SELL" else 0
        ok, reason = check_no_opposite_position(direction, positions, symbol=signal.symbol)
        if not ok:
            return False, reason

        if _is_vol_regime_signal(signal):
            return True, "ok"

        htf_bias = int(snapshot.get("htf_bias", 0) or 0)
        tf = signal.timeframe.upper()
        pa_tf = get_price_action_config(signal.symbol, to_legacy(signal.timeframe))
        if tf in ("M5", "5M"):
            require_htf = bool(pa_tf.get("REQUIRE_HTF_ALIGNMENT_M5", False))
        elif tf in ("M15", "15M"):
            require_htf = bool(pa_tf.get("REQUIRE_HTF_ALIGNMENT_M15", True))
        elif tf in ("H4", "4H"):
            require_htf = bool(pa_tf.get("REQUIRE_HTF_ALIGNMENT_H4", True))
        else:
            require_htf = False
        ok, reason = check_htf_alignment(direction, htf_bias, required=require_htf)
        if not ok:
            return False, reason

        df = snapshot.get("ohlcv")
        if isinstance(df, pd.DataFrame) and not df.empty:
            ok, reason = check_market_filters(
                df,
                pa_tf,
                strategy_mode=str(pa_tf.get("GOLD_STRATEGY_MODE", "")),
            )
            if not ok:
                return False, reason

        return True, "ok"

    def _live_spread_pips(self, broker_symbol: str, symbol: str) -> float:
        try:
            import MetaTrader5 as mt5

            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                return 999.0
            return spread_pips_from_prices(float(tick.ask), float(tick.bid), symbol)
        except Exception:
            return 999.0

    @staticmethod
    def _as_datetime(ts: object | None) -> datetime | None:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts
        if hasattr(ts, "to_pydatetime"):
            return ts.to_pydatetime()  # type: ignore[union-attr]
        return None

    def _adapt_xauusd_stop_for_tier(
        self,
        signal: TradingSignal,
        tier: AccountTier,
        portfolio_snapshot: dict,
    ) -> None:
        """Adapt XAUUSD SL/TP to tier profile instead of rejecting wide stops."""
        df = portfolio_snapshot.get("ohlcv")
        ohlcv = df if isinstance(df, pd.DataFrame) else None
        adapt_xauusd_stop_for_tier_signal(signal, tier, ohlcv)

    def _apply_micro_feasible_plan(
        self,
        signal: TradingSignal,
        computed_lot: float,
        tier: AccountTier,
        broker_symbol: str,
        portfolio_snapshot: dict | None = None,
    ) -> tuple[RiskDecision | None, float]:
        """MICRO capital-adaptive execution via feasible risk planner."""
        equity = float(self._account.equity)
        requested_pct = self._eval_risk_per_trade
        df = (portfolio_snapshot or {}).get("ohlcv")
        ohlcv = df if isinstance(df, pd.DataFrame) else None
        micro_decision, final_lot, diag = evaluate_micro_feasible_risk(
            signal,
            equity,
            tier=tier,
            requested_risk_pct=requested_pct,
            min_lot=self._min_lot,
            max_lot=self._max_lot,
            ohlcv=ohlcv,
            adapt_stop=False,
            log_rejections=True,
            broker_symbol=broker_symbol,
        )
        if micro_decision is not None:
            return micro_decision, computed_lot

        self._eval_risk_per_trade = float(
            diag.get("effective_risk_decimal", requested_pct)
        )
        if diag.get("adjusted"):
                from tradingbot.services.rejection_events import log_rejection_event

                feasible_msg = (
                    f"MICRO_FEASIBLE_EXECUTION "
                    f"target={diag['requested_risk_pct']:.2f}% "
                    f"effective={diag['effective_risk_pct']:.2f}% "
                    f"stop={diag['stop_pips_after']:.1f}p lot={final_lot:.2f}"
                )
                log_rejection_event(
                    stage="RISKGATE",
                    reason=feasible_msg,
                    symbol=signal.symbol,
                    direction=signal.direction.name,
                    context={
                        "target_risk_usd": diag.get("target_risk_usd"),
                        "actual_risk_usd": diag.get("actual_risk_usd"),
                        "raw_lot": diag.get("raw_lot"),
                        "final_lot": final_lot,
                    },
                )
                logger.info("[RiskGate] %s", feasible_msg)

        return None, final_lot

    def _reject_min_lot_over_risk(
        self, signal: TradingSignal, computed_lot: float, tier: AccountTier
    ) -> RiskDecision | None:
        """
        Reject when broker min lot would risk more than 2× configured dollar risk.

        Keeps lot-step rounding unchanged; only blocks the upward clamp to min_lot.
        """
        entry, sl = self._entry_and_sl(signal)
        if entry <= 0 or sl <= 0:
            return None

        equity = float(self._account.equity)
        target_risk_usd = round(equity * self._eval_risk_per_trade, 4)
        stop_distance = abs(entry - sl)
        stop_distance_pips = round(stop_distance / pip_size(signal.symbol), 2)
        cs = contract_size(signal.symbol)
        risk_per_unit = stop_distance * cs
        if risk_per_unit <= 0:
            return None

        raw_lot = (target_risk_usd / risk_per_unit) * risk_logic.regime_position_multiplier(self._regime)
        if raw_lot >= self._min_lot - 1e-9:
            return None

        actual_risk_usd = round(self._min_lot * risk_per_unit, 4)
        if actual_risk_usd <= target_risk_usd * self._min_lot_over_risk_multiplier:
            return None

        logger.warning(
            "[RiskGate] Rejecting trade: min lot would risk $%.2f vs allowed $%.2f",
            actual_risk_usd,
            target_risk_usd,
        )
        reason = (
            f"MIN_LOT_OVER_RISK "
            f"tier={tier.value} "
            f"target_risk_usd={target_risk_usd:.2f} "
            f"actual_risk_usd={actual_risk_usd:.2f} "
            f"stop_distance_pips={stop_distance_pips:.2f} "
            f"min_lot={self._min_lot:.2f} "
            f"raw_lot={raw_lot:.4f} computed_lot={computed_lot:.2f}"
        )
        return RiskDecision(allowed=False, reason=reason)

    @staticmethod
    def _entry_and_sl(signal: TradingSignal) -> tuple[float, float]:
        return entry_and_sl_from_signal(signal)

    def _compute_lot(
        self, signal: TradingSignal, portfolio_snapshot: dict, broker_symbol: str
    ) -> float:
        if signal.lot_size is not None:
            return signal.lot_size

        entry = float(getattr(signal, "entry_price", None) or 0.0)
        if entry <= 0 and signal.metadata:
            entry = float(signal.metadata.get("entry", signal.metadata.get("price", 0.0)) or 0.0)
        sl = float(signal.stop_loss or 0.0)
        if entry > 0 and sl > 0:
            return lot_from_stop_distance(
                self._account.equity,
                self._eval_risk_per_trade,
                entry,
                sl,
                signal.symbol,
                regime=self._regime,
                min_lot=self._min_lot,
                max_lot=self._max_lot,
            )

        df = portfolio_snapshot.get("ohlcv")
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return self._default_lot

        try:
            atr = risk_logic.atr_from_ohlcv(df)
            stop_pips = risk_logic.atr_to_stop_pips(atr, signal.symbol)
            return risk_logic.recommended_lot_size(
                self._account.equity,
                self._eval_risk_per_trade,
                stop_pips,
                signal.symbol,
                self._regime,
            )
        except Exception as e:
            logger.warning("Lot sizing fallback: %s", e)
            return self._fallback_lot()

    def _fallback_lot(self) -> float:
        allocation = self._account.balance * self._eval_risk_per_trade
        lot = round(max(self._min_lot, allocation / 1000), 2)
        return min(lot, self._max_lot)

    def _sync_mt5_account(self) -> None:
        from tradingbot.services.runtime_truth import get_live_equity, refresh_live_equity_from_mt5

        if not refresh_live_equity_from_mt5(log_freeze=True):
            return
        equity = get_live_equity()
        if equity is None or equity <= 0:
            return
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
            if info is None:
                return
            self._account.balance = float(info.balance)
            self._account.equity = float(info.equity)
            if self._initial_balance <= 0 or self._initial_balance > self._account.balance * 3:
                self._initial_balance = self._account.balance
            raw = mt5.positions_get()
            self._account.positions = list(raw) if raw else []
        except Exception:
            pass


def record_live_entry(timeframe: str) -> None:
    """پس از اجرای موفق سفارش — برای cooldown و شمارش روزانه."""
    _tracker.record_entry(timeframe)


def print_feasible_risk_validation_table() -> None:
    """Phase 39A — multi-balance planner diagnostics (existing module, no new files)."""
    assumptions = {
        "stop_distance_pips": 18.0,
        "requested_risk_pct": 0.0025,
        "min_lot": 0.01,
        "contract_size": 100.0,
        "pip_size": 0.1,
    }
    print("equity | tier | effective_risk_pct | executable | lot")
    for equity in (200, 300, 500, 1000, 5000):
        tier = detect_account_tier(float(equity))
        profile = execution_profile_for_tier(tier)
        req = profile.risk_per_trade_override or 0.005
        if tier != AccountTier.MICRO:
            req = profile.risk_per_trade_override or (0.005 if tier == AccountTier.SMALL else 0.005)
        plan = build_feasible_risk_plan(
            float(equity),
            float(req),
            assumptions["stop_distance_pips"],
            assumptions["min_lot"],
            assumptions["contract_size"],
            assumptions["pip_size"],
        )
        exe = "EXECUTABLE" if plan.can_execute else "REJECT"
        print(
            f"{equity} | {tier.value} | {plan.effective_risk_pct:.4f} | {exe} | {plan.final_lot:.2f}"
        )


def run_phase39a_balance_diagnostics() -> dict[int, dict[str, Any]]:
    """Return per-equity planner results for Phase 39A verification."""
    from tradingbot.domain.signal_helpers import compress_micro_stop_pips

    base_stop = 85.0
    compressed = compress_micro_stop_pips(base_stop, 0.56)
    out: dict[int, dict[str, Any]] = {}
    for equity in (200, 300, 500, 1000, 5000):
        tier = detect_account_tier(float(equity))
        profile = execution_profile_for_tier(tier)
        requested = (
            profile.risk_per_trade_override
            if profile.risk_per_trade_override is not None
            else 0.005
        )
        stop_pips = compressed if tier == AccountTier.MICRO else 18.0
        plan = build_feasible_risk_plan(
            float(equity),
            float(requested),
            stop_pips,
            0.01,
            100.0,
            0.1,
        )
        out[equity] = {
            "tier": tier.value,
            "stop_pips_after_compression": stop_pips,
            "requested_risk_pct": requested,
            "effective_risk_pct": plan.effective_risk_pct,
            "final_lot": plan.final_lot,
            "executable": plan.can_execute,
        }
    return out


if __name__ == "__main__":
    print_feasible_risk_validation_table()
