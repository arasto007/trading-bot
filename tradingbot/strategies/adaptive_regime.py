"""Adaptive multi-regime signal engine — profitability-tuned for XAUUSD M5."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from tradingbot.domain.filter_policy import is_session_filter_enabled
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    _multi_tf_trend_signal,
    _volatility_regime_signal,
)
from tradingbot.services.rejection_events import log_rejection_event, row_context
from tradingbot.strategies.vol_regime_signal import prepare_frame

logger = logging.getLogger(__name__)

Regime = str
DEFAULT_SYMBOL = "XAUUSD"
SignalFn = Callable[[pd.DataFrame, int], int | None]

REGIMES: tuple[str, ...] = ("TREND", "RANGE", "HIGH_VOLATILITY", "LOW_VOLATILITY", "NO_TRADE")

# Legacy fixed window (Phase 37B baseline) — superseded by resolve_xauusd_session_windows().
SESSION_HOURS: tuple[tuple[int, int], ...] = ((12, 17),)

# Regime-adaptive XAUUSD session windows (UTC, half-open [start, end)).
XAUUSD_SESSION_WINDOWS_UTC: dict[str, tuple[tuple[int, int], ...]] = {
    "HIGH_VOLATILITY": ((7, 19),),
    "TREND": ((8, 18),),
    "RANGE": ((11, 17),),
    "LOW_VOLATILITY": ((11, 17),),
}
_DEFAULT_SESSION_WINDOWS: tuple[tuple[int, int], ...] = ((11, 17),)

MIN_EMA_SEP = 0.00055
MIN_H1_TREND = True

_last_adaptive_session_log: tuple[str, tuple[tuple[int, int], ...], int, bool] | None = None
_last_micro_high_vol_block_log: int | None = None


def resolve_xauusd_session_windows(regime: str) -> tuple[tuple[int, int], ...]:
    """Return immutable UTC session windows for the active XAUUSD regime."""
    key = (regime or "").upper()
    if key == "NO_TRADE":
        return _DEFAULT_SESSION_WINDOWS
    windows = XAUUSD_SESSION_WINDOWS_UTC.get(key)
    return windows if windows is not None else _DEFAULT_SESSION_WINDOWS


def _bar_open_hour_utc(bar_open: pd.Timestamp) -> int:
    """Authoritative UTC hour from normalized bar open time."""
    ts = pd.Timestamp(bar_open)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.hour)


def _in_session(
    row: pd.Series,
    regime: str,
    *,
    bar_open: pd.Timestamp | None = None,
) -> bool:
    """True when bar open hour falls inside regime-specific UTC session windows."""
    hour = (
        _bar_open_hour_utc(bar_open)
        if bar_open is not None
        else int(row.get("hour_utc", 12))
    )
    windows = resolve_xauusd_session_windows(regime)
    return any(start <= hour < end for start, end in windows)


def _maybe_log_adaptive_session(
    regime: str,
    *,
    bar_open: pd.Timestamp | None = None,
    row: pd.Series | None = None,
) -> None:
    global _last_adaptive_session_log
    hour = (
        _bar_open_hour_utc(bar_open)
        if bar_open is not None
        else int((row or pd.Series()).get("hour_utc", 0))
    )
    windows = resolve_xauusd_session_windows(regime)
    in_sess = any(start <= hour < end for start, end in windows)
    state = (regime, windows, hour, in_sess)
    if state == _last_adaptive_session_log:
        return
    _last_adaptive_session_log = state
    logger.info(
        "Adaptive session | regime=%s windows=%s hour_utc=%d in_session=%s",
        regime,
        windows,
        hour,
        in_sess,
    )


@dataclass(frozen=True)
class AdaptiveSignal:
    direction: int
    regime: Regime
    strategy_id: str
    atr_pct: float
    atr_sl_mult: float
    tp_rr: float
    bar_index: int
    timestamp: pd.Timestamp
    quality_score: int | None = None
    score_components: dict | None = None
    quality_tier: str | None = None

    @property
    def side(self) -> str:
        return "BUY" if self.direction > 0 else "SELL"


def _h1_aligned(row: pd.Series, direction: int) -> bool:
    h1 = int(row.get("h1_trend", 0))
    if not MIN_H1_TREND:
        return True
    if direction > 0:
        return h1 >= 0
    return h1 <= 0


def _ema_sep_ok(row: pd.Series) -> bool:
    ema20, ema50, close = float(row["ema20"]), float(row["ema50"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, close)):
        return False
    return abs(ema20 - ema50) / max(close, 1.0) >= MIN_EMA_SEP


def _wrap(
    fn: SignalFn,
    *,
    log_rejections: bool = True,
) -> SignalFn:
    """H1 + EMA separation filter (session gate is authoritative in evaluate_adaptive_at_index)."""

    def _inner(frame: pd.DataFrame, idx: int) -> int | None:
        row = frame.iloc[idx]
        ctx = row_context(row)
        direction = fn(frame, idx)
        if direction not in (1, -1):
            return None
        dir_name = "BUY" if int(direction) > 0 else "SELL"
        if not _h1_aligned(row, int(direction)):
            if log_rejections:
                log_rejection_event(
                    stage="H1_ALIGN",
                    direction=dir_name,
                    reason=f"h1_trend={ctx.get('h1_trend')} blocks {dir_name}",
                    context=ctx,
                    symbol=DEFAULT_SYMBOL,
                )
            return None
        if not _ema_sep_ok(row):
            if log_rejections:
                log_rejection_event(
                    stage="EMA_SEP",
                    direction=dir_name,
                    reason=f"ema_sep_pct={ctx.get('ema_sep_pct')} < {MIN_EMA_SEP * 100:.4f}%",
                    context=ctx,
                    symbol=DEFAULT_SYMBOL,
                )
            return None
        return int(direction)

    return _inner


def _high_vol_momentum_signal(frame: pd.DataFrame, idx: int) -> int | None:
    row = frame.iloc[idx]
    atr_pct = float(row["atr_pct"])
    if not np.isfinite(atr_pct) or atr_pct < 0.72:
        return None
    ema20, ema50, close = float(row["ema20"]), float(row["ema50"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, close)):
        return None
    sep = abs(ema20 - ema50) / max(close, 1.0)
    if sep < MIN_EMA_SEP:
        return None
    rsi = float(row.get("rsi14", 50))
    if not np.isfinite(rsi):
        return None
    if ema20 > ema50 and close > ema20 and 45 <= rsi <= 72:
        return 1
    if ema20 < ema50 and close < ema20 and 28 <= rsi <= 55:
        return -1
    return None


def classify_regime(row: pd.Series) -> Regime:
    atr = float(row.get("atr_pct", 0.5))
    if not np.isfinite(atr):
        return "NO_TRADE"
    if atr >= 0.72:
        return "HIGH_VOLATILITY"
    if atr <= 0.28:
        return "LOW_VOLATILITY"
    ema20, ema50, close = float(row["ema20"]), float(row["ema50"]), float(row["close"])
    if not all(np.isfinite(x) for x in (ema20, ema50, close)):
        return "NO_TRADE"
    sep = abs(ema20 - ema50) / max(close, 1.0)
    h1 = int(row.get("h1_trend", 0))
    if sep >= MIN_EMA_SEP or h1 != 0:
        return "TREND"
    return "RANGE"


def _sl_tp_for_strategy(strategy_id: str) -> tuple[float, float]:
    presets: dict[str, tuple[float, float]] = {
        "VOL_REGIME": (2.0, 1.25),
        "HIGH_VOL_MOMENTUM": (3.0, 1.35),
        "MTF_TREND": (2.5, 1.5),
        "CONFLUENCE": (2.2, 1.6),
    }
    return presets.get(strategy_id, (2.5, 1.25))


def _confluence_only() -> bool:
    if os.getenv("ADAPTIVE_CONFLUENCE_ONLY", "").lower() in ("1", "true", "yes"):
        return True
    try:
        from tradingbot.config.live import get_live_config

        return bool(get_live_config().get("ADAPTIVE_CONFLUENCE_ONLY", False))
    except Exception:
        return False


def _confluence_mode() -> str:
    """Phase 44B: AND requires MTF+VOL agreement; OR accepts either leg."""
    raw = os.getenv("ADAPTIVE_CONFLUENCE_MODE", "").upper()
    if raw in ("AND", "OR"):
        return raw
    try:
        from tradingbot.config.live import get_live_config

        mode = str(get_live_config().get("ADAPTIVE_CONFLUENCE_MODE", "OR")).upper()
        return mode if mode in ("AND", "OR") else "OR"
    except Exception:
        return "OR"


def _disable_high_vol_for_micro() -> bool:
    raw = os.getenv("DISABLE_HIGH_VOL_FOR_MICRO", "").lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    try:
        from tradingbot.config.live import get_live_config

        return bool(get_live_config().get("DISABLE_HIGH_VOL_FOR_MICRO", False))
    except Exception:
        return False


def _resolve_account_tier_for_kill_switch() -> str | None:
    """MICRO kill switch tier — backtest equity override, else live MT5 equity."""
    bt_eq = os.environ.get("TRADINGBOT_BACKTEST_EQUITY")
    if bt_eq:
        from tradingbot.adapters.risk_gate import detect_account_tier

        try:
            return detect_account_tier(float(bt_eq)).value
        except (TypeError, ValueError):
            pass
    from tradingbot.ml.integration.factory import resolve_live_account_tier

    return resolve_live_account_tier()


def _maybe_log_micro_high_vol_blocked(atr_pct: float, bar_index: int) -> None:
    global _last_micro_high_vol_block_log
    if bar_index == _last_micro_high_vol_block_log:
        return
    _last_micro_high_vol_block_log = bar_index
    logger.info(
        "MICRO high-vol blocked | atr_pct=%.3f regime=HIGH_VOLATILITY",
        atr_pct,
    )


def _high_vol_continuation_dir(
    row: pd.Series,
    hvm_dir: int | None,
    atr_pct: float,
) -> int | None:
    """Option B: controlled trend continuation when MTF+HVM do not align."""
    if hvm_dir is None or atr_pct < 0.72:
        return None
    h1 = int(row.get("h1_trend", 0))
    if h1 != hvm_dir:
        return None
    rsi = float(row.get("rsi14", np.nan))
    if not np.isfinite(rsi):
        return None
    if hvm_dir > 0 and 48 <= rsi <= 75:
        return 1
    if hvm_dir < 0 and 25 <= rsi <= 52:
        return -1
    return None


def _quality_engine_path(
    frame: pd.DataFrame,
    idx: int,
    *,
    log_rejections: bool = True,
) -> AdaptiveSignal | None:
    """Phase 4A quality scoring — replaces AND-gate chain when enabled."""
    from tradingbot.strategies.adaptive_quality_engine import evaluate_quality_at_index

    row = frame.iloc[idx]
    regime = classify_regime(row)
    atr_pct = float(row["atr_pct"]) if np.isfinite(float(row.get("atr_pct", np.nan))) else 0.5
    score_result, _ctx = evaluate_quality_at_index(frame, idx, log_rejections=log_rejections)
    if score_result is None:
        return None
    direction = int(score_result.direction or 0)
    if direction not in (1, -1):
        return None
    return AdaptiveSignal(
        direction=direction,
        regime=regime,
        strategy_id="QUALITY_ENGINE",
        atr_pct=atr_pct,
        atr_sl_mult=2.2,
        tp_rr=1.6,
        bar_index=idx,
        timestamp=pd.Timestamp(frame.index[idx]),
        quality_score=score_result.quality_score,
        score_components=dict(score_result.score_components),
        quality_tier=score_result.tier,
    )


def evaluate_adaptive_at_index(
    frame: pd.DataFrame,
    idx: int,
    *,
    log_rejections: bool = True,
    use_quality_engine: bool | None = None,
) -> AdaptiveSignal | None:
    if idx < 0 or idx >= len(frame):
        return None
    if use_quality_engine is None:
        from tradingbot.strategies.adaptive_quality_engine import quality_engine_enabled

        use_quality_engine = quality_engine_enabled()
    if use_quality_engine:
        return _quality_engine_path(frame, idx, log_rejections=log_rejections)
    row = frame.iloc[idx]
    ctx = row_context(row)
    bar_open = pd.Timestamp(frame.index[idx])
    regime = classify_regime(row)
    ctx["regime"] = regime
    _maybe_log_adaptive_session(regime, bar_open=bar_open, row=row)

    if is_session_filter_enabled() and not _in_session(row, regime, bar_open=bar_open):
        if log_rejections:
            windows = resolve_xauusd_session_windows(regime)
            log_rejection_event(
                stage="SESSION",
                direction=None,
                reason=f"hour_utc={ctx.get('hour_utc')} outside {windows} regime={regime}",
                context=ctx,
                symbol=DEFAULT_SYMBOL,
            )
        return None

    atr_pct = float(row["atr_pct"]) if np.isfinite(float(row.get("atr_pct", np.nan))) else 0.5

    if (
        regime == "HIGH_VOLATILITY"
        and _disable_high_vol_for_micro()
        and _resolve_account_tier_for_kill_switch() == "MICRO"
    ):
        _maybe_log_micro_high_vol_blocked(atr_pct, idx)
        if log_rejections:
            log_rejection_event(
                stage="REGIME",
                direction=None,
                reason="MICRO high-vol kill switch",
                context={**ctx, "atr_pct": round(atr_pct, 4), "account_tier": "MICRO"},
                symbol=DEFAULT_SYMBOL,
            )
        return None

    if regime == "NO_TRADE":
        if log_rejections:
            log_rejection_event(
                stage="REGIME",
                direction=None,
                reason="regime=NO_TRADE",
                context=ctx,
                symbol=DEFAULT_SYMBOL,
            )
        return None

    mtf = _wrap(_multi_tf_trend_signal, log_rejections=log_rejections)
    vol = _wrap(_volatility_regime_signal, log_rejections=log_rejections)
    hvm = _wrap(_high_vol_momentum_signal, log_rejections=log_rejections)

    if _confluence_only():
        mtf_dir = mtf(frame, idx)
        vol_dir = vol(frame, idx) if 0.30 <= atr_pct <= 0.70 else None
        confluence_dir: int | None = None
        if _confluence_mode() == "OR":
            if mtf_dir in (1, -1):
                confluence_dir = int(mtf_dir)
            elif vol_dir in (1, -1):
                confluence_dir = int(vol_dir)
        elif mtf_dir and vol_dir and mtf_dir == vol_dir:
            confluence_dir = int(mtf_dir)
        if confluence_dir is not None:
            strategy_id = "CONFLUENCE"
            sl_mult, tp_rr = (2.0, 2.0)
            return AdaptiveSignal(
                direction=confluence_dir,
                regime=regime,
                strategy_id=strategy_id,
                atr_pct=atr_pct,
                atr_sl_mult=sl_mult,
                tp_rr=tp_rr,
                bar_index=idx,
                timestamp=pd.Timestamp(frame.index[idx]),
            )
        if regime == "HIGH_VOLATILITY" and atr_pct >= 0.72:
            hvm_dir = hvm(frame, idx)
            if hvm_dir and mtf_dir and hvm_dir == mtf_dir:
                sl_mult, tp_rr = _sl_tp_for_strategy("HIGH_VOL_MOMENTUM")
                return AdaptiveSignal(
                    direction=int(hvm_dir),
                    regime=regime,
                    strategy_id="HIGH_VOL_MOMENTUM",
                    atr_pct=atr_pct,
                    atr_sl_mult=sl_mult,
                    tp_rr=tp_rr,
                    bar_index=idx,
                    timestamp=pd.Timestamp(frame.index[idx]),
                )
            cont_dir = _high_vol_continuation_dir(row, hvm_dir, atr_pct)
            if cont_dir is not None:
                logger.info(
                    "High-vol continuation signal | direction=%s regime=HIGH_VOLATILITY "
                    "atr_pct=%.3f rsi14=%.2f h1_trend=%d",
                    "BUY" if cont_dir > 0 else "SELL",
                    atr_pct,
                    float(row.get("rsi14", 0)),
                    int(row.get("h1_trend", 0)),
                )
                sl_mult, tp_rr = _sl_tp_for_strategy("HIGH_VOL_MOMENTUM")
                return AdaptiveSignal(
                    direction=int(cont_dir),
                    regime=regime,
                    strategy_id="HIGH_VOL_MOMENTUM",
                    atr_pct=atr_pct,
                    atr_sl_mult=sl_mult,
                    tp_rr=tp_rr,
                    bar_index=idx,
                    timestamp=pd.Timestamp(frame.index[idx]),
                )
        if log_rejections:
            parts = []
            if mtf_dir is None:
                parts.append("no_mtf_signal")
            if vol_dir is None and 0.30 <= atr_pct <= 0.70:
                parts.append("no_vol_signal")
            elif vol_dir is None:
                parts.append(f"atr_pct={atr_pct:.3f}_outside_0.30-0.70")
            elif (
                _confluence_mode() == "AND"
                and mtf_dir
                and vol_dir
                and mtf_dir != vol_dir
            ):
                parts.append(f"mtf={mtf_dir}_vol={vol_dir}_disagree")
            elif _confluence_mode() == "OR" and mtf_dir is None and vol_dir is None:
                parts.append("mtf_or_vol_unavailable")
            if regime == "HIGH_VOLATILITY" and atr_pct >= 0.72:
                parts.append("high_vol_hvm_mtf_no_agreement")
            log_rejection_event(
                stage="CONFLUENCE",
                direction="BUY" if mtf_dir == 1 else ("SELL" if mtf_dir == -1 else None),
                reason="; ".join(parts) or "confluence_not_met",
                context={**ctx, "atr_pct": round(atr_pct, 4), "mtf_dir": mtf_dir, "vol_dir": vol_dir},
                symbol=DEFAULT_SYMBOL,
            )
        return None

    if regime == "HIGH_VOLATILITY":
        candidates: list[tuple[str, SignalFn]] = [
            ("MTF_TREND", mtf),
            ("HIGH_VOL_MOMENTUM", hvm),
        ]
    elif regime in ("LOW_VOLATILITY", "RANGE"):
        candidates = [("MTF_TREND", mtf)]
    elif regime == "TREND":
        candidates = [
            ("MTF_TREND", mtf),
            ("VOL_REGIME", vol),
        ]
    else:
        return None

    for strategy_id, fn in candidates:
        direction = fn(frame, idx)
        if direction in (1, -1):
            sl_mult, tp_rr = _sl_tp_for_strategy(strategy_id)
            return AdaptiveSignal(
                direction=int(direction),
                regime=regime,
                strategy_id=strategy_id,
                atr_pct=atr_pct,
                atr_sl_mult=sl_mult,
                tp_rr=tp_rr,
                bar_index=idx,
                timestamp=pd.Timestamp(frame.index[idx]),
            )
    return None


def prepare_adaptive_frame(candles: pd.DataFrame) -> pd.DataFrame:
    return prepare_frame(candles)
