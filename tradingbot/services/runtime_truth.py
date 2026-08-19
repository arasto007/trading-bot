"""Runtime truth snapshot — what the live bot actually uses."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.config.live import PRIMARY_SYMBOL

CANONICAL_SYMBOL = PRIMARY_SYMBOL

ROOT = Path(__file__).resolve().parents[2]

# Shared live equity state — single source for tier/sizing on the live path.
_live_equity_state: dict[str, Any] = {
    "equity": None,
    "balance": None,
    "last_good_equity": None,
    "last_good_balance": None,
    "last_good_at": None,
    "entries_frozen": False,
    "mt5_read_ok": False,
    "locked_at_startup": False,
}

_market_data_state: dict[str, Any] = {
    "last_bar_time_utc": None,
    "bar_age_minutes": None,
    "market_data_stale": False,
}

_mt5_tz_state: dict[str, Any] = {
    "offset_seconds": 0,
    "detected_at": None,
}


def detect_mt5_utc_offset_seconds(
    latest_bar_utc: datetime,
    *,
    timeframe_minutes: int = 5,
) -> int:
    """
    Detect broker-server skew when MT5 bar timestamps run ahead of wall UTC.

    LiteFinance and similar brokers expose server-local times via epoch fields
    that Python interprets as UTC, producing a stable whole-hour offset.
    """
    now = datetime.now(timezone.utc)
    if latest_bar_utc.tzinfo is None:
        latest_bar_utc = latest_bar_utc.replace(tzinfo=timezone.utc)
    else:
        latest_bar_utc = latest_bar_utc.astimezone(timezone.utc)
    tolerance = timedelta(minutes=timeframe_minutes + 2)
    skew = latest_bar_utc - now
    if skew <= tolerance:
        return 0
    offset_hours = round(skew.total_seconds() / 3600)
    return max(0, offset_hours * 3600)


def normalize_mt5_bar_index(
    df: pd.DataFrame,
    *,
    timeframe_minutes: int = 5,
) -> pd.DataFrame:
    """Shift MT5 OHLCV index from broker-server time to true UTC when skewed."""
    import logging

    logger = logging.getLogger(__name__)
    if df is None or df.empty:
        return df
    out = df.copy()
    idx = pd.to_datetime(out.index, utc=True)
    latest = idx[-1].to_pydatetime()
    offset_sec = detect_mt5_utc_offset_seconds(
        latest, timeframe_minutes=timeframe_minutes
    )
    if offset_sec > 0:
        cached_offset = int(_mt5_tz_state.get("offset_seconds") or 0)
        if cached_offset != offset_sec:
            _mt5_tz_state["offset_seconds"] = offset_sec
            _mt5_tz_state["detected_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("MT5 bar timezone corrected | offset_seconds=%d", offset_sec)
        idx = idx - pd.Timedelta(seconds=offset_sec)
    out.index = idx
    return out


def mt5_rates_to_ohlcv_dataframe(
    rates: Any,
    *,
    timeframe_minutes: int = 5,
) -> pd.DataFrame:
    """Convert MT5 rate rows to a UTC-normalized OHLCV DataFrame."""
    from tradingbot.domain.ohlcv import normalize_ohlcv

    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = normalize_ohlcv(df)
    return normalize_mt5_bar_index(df, timeframe_minutes=timeframe_minutes)


def mt5_timezone_metadata() -> dict[str, Any]:
    return {
        "mt5_utc_offset_seconds": int(_mt5_tz_state.get("offset_seconds") or 0),
        "mt5_utc_offset_detected_at": _mt5_tz_state.get("detected_at"),
    }


def is_market_data_stale(last_bar_time_utc: datetime, *, max_age_minutes: int = 15) -> bool:
    """Return True if the last M5 bar is older than max_age_minutes."""
    if last_bar_time_utc.tzinfo is None:
        last_bar_time_utc = last_bar_time_utc.replace(tzinfo=timezone.utc)
    else:
        last_bar_time_utc = last_bar_time_utc.astimezone(timezone.utc)
    age_minutes = (datetime.now(timezone.utc) - last_bar_time_utc).total_seconds() / 60.0
    return age_minutes > max_age_minutes


def _bar_age_minutes(last_bar_time_utc: datetime | None) -> float | None:
    if last_bar_time_utc is None:
        return None
    if last_bar_time_utc.tzinfo is None:
        last_bar_time_utc = last_bar_time_utc.replace(tzinfo=timezone.utc)
    else:
        last_bar_time_utc = last_bar_time_utc.astimezone(timezone.utc)
    return (datetime.now(timezone.utc) - last_bar_time_utc).total_seconds() / 60.0


def update_market_data_state(
    last_bar_time_utc: datetime | None,
    *,
    max_age_minutes: int = 15,
    log_stale: bool = True,
) -> dict[str, Any]:
    """Refresh shared stale-bar state from the latest M5 bar timestamp."""
    import logging

    logger = logging.getLogger(__name__)
    age = _bar_age_minutes(last_bar_time_utc)
    stale = True if last_bar_time_utc is None else is_market_data_stale(
        last_bar_time_utc, max_age_minutes=max_age_minutes
    )
    was_stale = bool(_market_data_state.get("market_data_stale"))
    _market_data_state.update(
        {
            "last_bar_time_utc": last_bar_time_utc.isoformat() if last_bar_time_utc else None,
            "bar_age_minutes": round(age, 1) if age is not None else None,
            "market_data_stale": stale,
        }
    )
    if stale and log_stale and (not was_stale or age is not None):
        age_label = f"{age:.1f}m" if age is not None else "unknown"
        logger.warning("Market data stale — entries frozen | age=%s", age_label)
    return market_data_metadata()


def market_data_stale() -> bool:
    return bool(_market_data_state.get("market_data_stale"))


def market_data_metadata() -> dict[str, Any]:
    return {
        "market_data_stale": bool(_market_data_state.get("market_data_stale")),
        "last_bar_time_utc": _market_data_state.get("last_bar_time_utc"),
        "bar_age_minutes": _market_data_state.get("bar_age_minutes"),
    }


def resolve_entries_frozen_reason() -> str | None:
    if bool(_live_equity_state.get("entries_frozen")):
        return "mt5_equity"
    if market_data_stale():
        return "stale_market_data"
    return None


LIVE_ACCOUNT_CACHE = ROOT / "data" / "live_account.json"


def write_live_account_cache() -> None:
    """Persist MT5 balance for HTA dashboard while bot holds IPC lock."""
    bal = _live_equity_state.get("balance")
    eq = _live_equity_state.get("equity")
    if bal is None and eq is None:
        return
    profit = None
    try:
        if bal is not None and eq is not None:
            profit = round(float(eq) - float(bal), 2)
    except (TypeError, ValueError):
        profit = None
    payload = {
        "balance": round(float(bal), 2) if bal is not None else None,
        "equity": round(float(eq), 2) if eq is not None else None,
        "profit": profit,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        LIVE_ACCOUNT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_ACCOUNT_CACHE.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def refresh_live_equity_from_mt5(*, log_freeze: bool = True) -> bool:
    """Read MT5 account_info; update shared state. Returns True if equity is valid."""
    import logging

    logger = logging.getLogger(__name__)
    try:
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            _live_equity_state["mt5_read_ok"] = False
            _live_equity_state["entries_frozen"] = True
            if log_freeze and _live_equity_state.get("last_good_equity") is not None:
                logger.warning("MT5 equity unavailable — freezing new entries")
                logger.info("Existing positions management remains active")
            return False
        equity = float(info.equity)
        balance = float(info.balance)
        if equity <= 0:
            _live_equity_state["mt5_read_ok"] = False
            _live_equity_state["entries_frozen"] = True
            return False
        now = datetime.now(timezone.utc).isoformat()
        _live_equity_state.update(
            {
                "equity": equity,
                "balance": balance,
                "last_good_equity": equity,
                "last_good_balance": balance,
                "last_good_at": now,
                "entries_frozen": False,
                "mt5_read_ok": True,
            }
        )
        write_live_account_cache()
        return True
    except Exception:
        _live_equity_state["mt5_read_ok"] = False
        _live_equity_state["entries_frozen"] = True
        if log_freeze:
            logger.warning("MT5 equity unavailable — freezing new entries")
            logger.info("Existing positions management remains active")
        return False


def lock_live_equity_at_startup() -> tuple[bool, float | None]:
    """
    Require real MT5 equity before entering the trading loop.
    Returns (ok, equity).
    """
    import logging

    logger = logging.getLogger(__name__)
    if not refresh_live_equity_from_mt5(log_freeze=False):
        info = None
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
        except Exception:
            pass
        if info is None:
            logger.error("MT5 account info unavailable")
            return False, None
        logger.error("Invalid MT5 equity")
        return False, None
    equity = float(_live_equity_state["equity"])
    _live_equity_state["locked_at_startup"] = True
    return True, equity


def get_live_equity() -> float | None:
    """Current or last-known MT5 equity for live tier resolution."""
    if _live_equity_state.get("equity") is not None:
        return float(_live_equity_state["equity"])
    last = _live_equity_state.get("last_good_equity")
    return float(last) if last is not None else None


def entries_frozen() -> bool:
    return bool(_live_equity_state.get("entries_frozen"))


def live_equity_metadata() -> dict[str, Any]:
    """Equity source fields for runtime truth."""
    ok = bool(_live_equity_state.get("mt5_read_ok"))
    equity = get_live_equity()
    last_at = _live_equity_state.get("last_good_at")
    return {
        "equity_source": "MT5" if ok else ("LAST_KNOWN" if equity is not None else "UNAVAILABLE"),
        "mt5_equity_read_ok": ok,
        "equity_timestamp_utc": last_at or datetime.now(timezone.utc).isoformat(),
        "fallback_used": not ok and equity is not None,
        "entries_frozen": entries_frozen(),
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_raw(name: str) -> str | None:
    return os.environ.get(name)


def collect_runtime_truth(*, legacy_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-serializable snapshot of active live configuration."""
    from tradingbot.config.live import get_live_config
    from tradingbot.ml.integration.config import is_ml_kernel_enabled, is_ml_kernel_env_set
    from tradingbot.ml.integration.startup_diagnostics import resolve_engine_selection
    from tradingbot.services.execution_mode import is_dry_run, is_paper, mode_label
    from tradingbot.services.signal_filter_mode import (
        resolve_signal_filter_mode,
        resolve_wpsqf_threshold,
    )
    from tradingbot.strategies.adaptive_regime import XAUUSD_SESSION_WINDOWS_UTC

    from tradingbot.config.price_action import PA_COOLDOWN_BARS, get_price_action_config

    live = get_live_config()
    cfg = legacy_config or {}
    pa = cfg.get("PRICE_ACTION", {})
    # Publish PA cooldown for live parity (VOL stays on its own key).
    pa_m5 = get_price_action_config(PRIMARY_SYMBOL, "M5")
    pa_cooldown_bars = int(
        pa_m5.get(
            "COOLDOWN_BARS",
            pa.get("COOLDOWN_BARS", cfg.get("COOLDOWN_BARS", PA_COOLDOWN_BARS)),
        )
    )
    vol_cooldown_bars = int(live.get("VOL_REGIME_COOLDOWN_BARS", 12))
    selection = resolve_engine_selection()

    wpsqf_mode = resolve_signal_filter_mode(config=cfg)
    risk_per_trade = float(
        live.get("RISK_PER_TRADE", cfg.get("RISK_PER_TRADE", 0.005))
    )

    exit_modes: list[str] = []
    if bool(live.get("EOD_CLOSE_ENABLED", pa.get("EOD_CLOSE_ENABLED", True))):
        exit_modes.append(
            f"EOD_CLOSE@{live.get('EOD_HOUR', pa.get('EOD_HOUR', 23))}:"
            f"{live.get('EOD_MINUTE', pa.get('EOD_MINUTE', 55)):02d}"
        )
    if bool(pa.get("FRIDAY_CLOSE_ENABLED", True)):
        exit_modes.append(
            f"FRIDAY_CLOSE@{pa.get('FRIDAY_CLOSE_HOUR', 20)}:"
            f"{pa.get('FRIDAY_CLOSE_MINUTE', 0):02d}"
        )
    exit_modes.append("TRAILING_STOP_ATR")
    if bool(pa.get("ENABLE_PARTIAL_TP", True)):
        exit_modes.append("PARTIAL_TP_1R_2R_3R")
    exit_modes.append(f"EMERGENCY_MAX_LOSS_PIPS={cfg.get('EMERGENCY_MAX_LOSS_PIPS', pa.get('EMERGENCY_MAX_LOSS_PIPS', 50))}")
    exit_modes.append("BROKER_SL_TP")

    session_windows = [
        f"{regime}:{','.join(f'{s:02d}-{e:02d}' for s, e in wins)} UTC"
        for regime, wins in XAUUSD_SESSION_WINDOWS_UTC.items()
    ]

    refresh_live_equity_from_mt5(log_freeze=False)
    equity = get_live_equity()
    if equity is None:
        equity = _resolve_live_equity(default=0.0)
    from tradingbot.adapters.adaptive_regime_strategy_registry import duplicate_signal_cache_size
    from tradingbot.adapters.risk_gate import capital_adaptive_snapshot
    from tradingbot.adapters.symbols import resolve_broker_symbol

    # Phase 39A: capital_adaptive_snapshot includes requested/effective risk,
    # micro_risk_adjusted, feasible_execution, actual_risk_at_min_lot_usd.
    capital_adaptive = capital_adaptive_snapshot(
        equity if equity and equity > 0 else 0.0,
        config_risk_per_trade=risk_per_trade,
        stop_distance_pips=18.0,
        min_lot=float(cfg.get("MIN_LOT_SIZE", 0.01)),
    )
    broker_symbol = resolve_broker_symbol(CANONICAL_SYMBOL, cfg)

    truth = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_strategy_engine": selection.selected_engine,
        "engine_selection_reason": selection.reason,
        "execution_mode": mode_label(),
        "dry_run": is_dry_run(),
        "paper": is_paper(),
        "USE_ML_KERNEL": _env_raw("USE_ML_KERNEL"),
        "USE_ML_KERNEL_enabled": is_ml_kernel_enabled(),
        "USE_ML_KERNEL_env_set": is_ml_kernel_env_set(),
        "ADAPTIVE_REGIME_ENABLED": bool(live.get("ADAPTIVE_REGIME_ENABLED", False)),
        "ADAPTIVE_CONFLUENCE_ONLY": bool(live.get("ADAPTIVE_CONFLUENCE_ONLY", False)),
        "VOL_REGIME_ENABLED": bool(live.get("VOL_REGIME_ENABLED", False)),
        "VOL_REGIME_SKIP_TQ": bool(live.get("VOL_REGIME_SKIP_TQ", True)),
        "WPSQF": {
            "mode": wpsqf_mode.value,
            "threshold": resolve_wpsqf_threshold(config=cfg),
            "active": wpsqf_mode.value != "OFF",
        },
        "risk_per_trade_pct": round(risk_per_trade * 100, 3),
        "vol_regime_risk_per_trade_pct": float(live.get("VOL_REGIME_RISK_PER_TRADE_PCT", 0.5)),
        "cooldown_bars": pa_cooldown_bars,
        "pa_cooldown_bars": pa_cooldown_bars,
        "vol_regime_cooldown_bars": vol_cooldown_bars,
        "max_trades_per_day": int(live.get("VOL_REGIME_MAX_TRADES_PER_DAY", 3)),
        "max_concurrent_positions": int(live.get("VOL_REGIME_MAX_CONCURRENT", 1)),
        "max_open_positions_total": int(live.get("MAX_OPEN_POSITIONS_TOTAL", 3)),
        "session_window_utc": session_windows,
        "symbols": list(live.get("SYMBOLS", [PRIMARY_SYMBOL])),
        "timeframes": list(live.get("TIMEFRAMES", ["5m"])),
        "loop_interval_seconds": int(live.get("LOOP_INTERVAL", 30)),
        "exit_modes_active": exit_modes,
        "filters_skipped_for_adaptive": [
            "WPSQF (if OFF)",
            "TradeQuality",
            "MetaLabeler",
            "HTF_alignment",
            "PA_market_filters",
        ],
        "max_spread_pips_xau": max(
            float(pa.get("MAX_SPREAD_PIPS", 5.0)), 15.0
        ),
        "max_daily_risk_pct": float(live.get("MAX_DAILY_RISK", 0.04)) * 100,
    }
    truth.update(capital_adaptive)
    truth.update(live_equity_metadata())
    truth.update(market_data_metadata())
    truth.update(
        {
            "canonical_symbol": CANONICAL_SYMBOL,
            "broker_symbol": broker_symbol,
            "entries_frozen_reason": resolve_entries_frozen_reason(),
            "duplicate_signal_cache_size": duplicate_signal_cache_size(),
        }
    )
    truth.update(mt5_timezone_metadata())
    return truth


def _resolve_live_equity(default: float = 0.0) -> float:
    """Best-effort live equity for capital-adaptive runtime truth."""
    equity = get_live_equity()
    if equity is not None and equity > 0:
        return equity
    if refresh_live_equity_from_mt5(log_freeze=False):
        return float(_live_equity_state["equity"])
    return default


def format_runtime_truth_console(truth: dict[str, Any]) -> str:
    eff_risk = truth.get("effective_risk_per_trade", truth.get("risk_per_trade_pct", 0) / 100)
    lines = [
        "=" * 60,
        "RUNTIME TRUTH REPORT",
        "=" * 60,
        f"Generated: {truth['generated_at']}",
        f"Active engine: {truth['active_strategy_engine']}",
        f"  Reason: {truth['engine_selection_reason']}",
        f"Execution mode: {truth['execution_mode']}",
        "",
        "--- Engine flags ---",
        f"USE_ML_KERNEL={truth['USE_ML_KERNEL']} enabled={truth['USE_ML_KERNEL_enabled']}",
        f"ADAPTIVE_REGIME_ENABLED={truth['ADAPTIVE_REGIME_ENABLED']}",
        f"ADAPTIVE_CONFLUENCE_ONLY={truth['ADAPTIVE_CONFLUENCE_ONLY']}",
        "",
        "--- Risk ---",
        f"Risk per trade: {truth['risk_per_trade_pct']}%",
        f"Cooldown bars (PA): {truth['cooldown_bars']}",
        f"VOL regime cooldown bars: {truth.get('vol_regime_cooldown_bars', 'n/a')}",
        f"Max trades/day: {truth['max_trades_per_day']}",
        f"Max concurrent: {truth['max_concurrent_positions']}",
        f"Account tier: {truth.get('account_tier', 'UNKNOWN')} equity={truth.get('account_equity', 0)}",
        f"Effective risk/trade: {eff_risk}",
        f"Effective SL multiplier: {truth.get('effective_sl_multiplier', truth.get('effective_confluence_sl_mult', 2.2))}",
        f"Effective confluence SL mult: {truth.get('effective_confluence_sl_mult', 2.2)}",
        f"Trading style: {truth.get('trading_style', 'UNKNOWN')}",
        f"Capital adaptive mode: {truth.get('capital_adaptive_mode', 'UNKNOWN')}",
        f"Effective max hold bars: {truth.get('effective_max_hold_bars', 72)}",
        f"Breakeven enabled: {truth.get('breakeven_enabled', False)}",
        f"Partial close enabled: {truth.get('partial_close_enabled', False)}",
        f"ATR trailing enabled: {truth.get('atr_trailing_enabled', False)}",
        f"Time exit enabled: {truth.get('time_exit_enabled', False)}",
        f"Trailing ATR multiplier: {truth.get('trailing_atr_multiplier')}",
        f"Stagnation bars limit: {truth.get('stagnation_bars_limit')}",
        "",
        "--- Capital-adaptive execution profile ---",
        f"Enabled: {truth.get('capital_adaptive_enabled', False)}",
    ]
    profile = truth.get("execution_profile") or {}
    if profile:
        lines.append(f"Confidence threshold: {profile.get('confidence_threshold')}")
        lines.append(f"Max positions/symbol: {profile.get('max_positions_per_symbol')}")
        lines.append(f"Require H1 alignment: {profile.get('require_h1_alignment')}")
        lines.append(f"Require full confluence: {profile.get('require_full_confluence')}")
    sw = ", ".join(truth["session_window_utc"])
    sy = ", ".join(truth["symbols"])
    tf = ", ".join(truth["timeframes"])
    wpsqf = truth["WPSQF"]
    lines.extend([
        "",
        "--- Session / markets ---",
        f"Session window: {sw}",
        f"Symbols: {sy}",
        f"Timeframes: {tf}",
        "",
        "--- WPSQF ---",
        f"State: {wpsqf['mode']} active={wpsqf['active']}",
        f"Threshold: {wpsqf['threshold']}",
        "",
        "--- Exit modes (active) ---",
    ])
    for mode in truth["exit_modes_active"]:
        lines.append(f"  - {mode}")
    lines.append("=" * 60)
    return "\n".join(lines)


def write_runtime_truth(
    *,
    legacy_config: dict[str, Any] | None = None,
    output_path: Path | None = None,
    print_console: bool = True,
) -> dict[str, Any]:
    truth = collect_runtime_truth(legacy_config=legacy_config)
    path = output_path or (ROOT / "logs" / "runtime_truth.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")
    if print_console:
        print(format_runtime_truth_console(truth))
        print(f"Written to: {path}")
    return truth
