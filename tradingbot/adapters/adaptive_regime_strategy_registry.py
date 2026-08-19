"""Adaptive multi-regime strategy registry — routes to best sub-engine per market phase."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.timeframes import to_kernel
from tradingbot.config.live import get_live_config
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.domain.signal_helpers import compute_sl_tp
from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE
from tradingbot.ml.integration.factory import resolve_live_account_tier
from tradingbot.ports.strategies import IStrategyRegistry
from tradingbot.strategies.adaptive_regime import (
    classify_regime,
    evaluate_adaptive_at_index,
    prepare_adaptive_frame,
)
from tradingbot.strategies.vol_regime_signal import DEFAULT_SYMBOL, DEFAULT_TIMEFRAME

logger = logging.getLogger(__name__)

STRATEGY_ID = "ADAPTIVE_REGIME"
DEFAULT_SYMBOL_K = DEFAULT_SYMBOL
DEFAULT_TF = DEFAULT_TIMEFRAME

_DEDUP_WINDOW = timedelta(minutes=10)
_last_signal_keys: dict[str, datetime] = {}


def duplicate_signal_cache_size() -> int:
    return len(_last_signal_keys)


def _prune_dedup_cache(now: datetime) -> None:
    cutoff = now - _DEDUP_WINDOW
    for key, seen_at in list(_last_signal_keys.items()):
        if seen_at < cutoff:
            del _last_signal_keys[key]


def _repair_live_atr_pct(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Recompute atr_pct for live bars when research rolling(500) lacks history.

    prepare_frame uses rolling(500, min_periods=100) on atr14; with ~100-300
    live M5 bars the last atr_pct stays NaN and forces regime=NO_TRADE.
    """
    if frame.empty or "atr14" not in frame.columns:
        return frame
    last = frame["atr_pct"].iloc[-1] if "atr_pct" in frame.columns else np.nan
    if last is not None and np.isfinite(last):
        return frame
    out = frame.copy()
    n = len(out)
    window = min(max(n, 50), 500)
    min_periods = min(50, max(14, n - 13))
    out["atr_pct"] = out["atr14"].rolling(window, min_periods=min_periods).rank(pct=True)
    return out


def _is_duplicate_signal(symbol: str, direction: str, bar_time: Any) -> bool:
    now = datetime.now(timezone.utc)
    _prune_dedup_cache(now)
    if hasattr(bar_time, "to_pydatetime"):
        bar_time = bar_time.to_pydatetime()
    if getattr(bar_time, "tzinfo", None) is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    else:
        bar_time = bar_time.astimezone(timezone.utc)
    key = f"{symbol.upper()}|{direction}|{bar_time.isoformat()}"
    prev = _last_signal_keys.get(key)
    if prev is not None and now - prev < _DEDUP_WINDOW:
        logger.info("Duplicate signal suppressed | key=%s", key)
        return True
    _last_signal_keys[key] = now
    return False


class AdaptiveRegimeStrategyRegistry(IStrategyRegistry):
    """Production adaptive router — VOL / trend / range / high-vol / session."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or load_legacy_config())
        live = get_live_config()
        self._enabled = bool(live.get("ADAPTIVE_REGIME_ENABLED", True))
        self._risk_pct = float(
            live.get("VOL_REGIME_RISK_PER_TRADE_PCT")
            or self._config.get("RISK_PER_TRADE", 0.005) * 100
            or 1.0
        )
        self._last_regime: str | None = None
        logger.info(
            "AdaptiveRegimeStrategyRegistry active | symbol=%s tf=%s risk=%.2f%%",
            DEFAULT_SYMBOL_K,
            DEFAULT_TF,
            self._risk_pct,
        )

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        def _rej(reason: str) -> None:
            try:
                from tradingbot.services.engine_telemetry import ENGINE_ADAPTIVE, get_engine_telemetry

                get_engine_telemetry().record_rejection(
                    ENGINE_ADAPTIVE,
                    reason=reason,
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                )
            except Exception:
                pass

        if not self._enabled or df is None or df.empty:
            _rej("disabled_or_empty")
            return None

        kernel_tf = to_kernel(market.timeframe)
        if market.symbol.upper() != DEFAULT_SYMBOL_K or kernel_tf != DEFAULT_TF:
            _rej("wrong_symbol_or_timeframe")
            return None

        from tradingbot.services.runtime_truth import normalize_mt5_bar_index

        df = normalize_mt5_bar_index(df)
        frame = _repair_live_atr_pct(prepare_adaptive_frame(df))
        if frame.empty:
            _rej("empty_frame")
            return None

        idx = len(frame) - 1
        row = frame.iloc[idx]
        regime = classify_regime(row)
        if regime != self._last_regime:
            logger.info(
                "Adaptive regime → %s | bar=%s atr_pct=%.3f",
                regime,
                frame.index[idx],
                float(row.get("atr_pct", 0)),
            )
            self._last_regime = regime

        sig = evaluate_adaptive_at_index(frame, idx)
        if sig is None:
            logger.debug(
                "Adaptive no setup | regime=%s bar=%s atr=%.3f",
                regime,
                frame.index[idx],
                float(row.get("atr_pct", 0)),
            )
            _rej(f"no_setup:{regime}")
            return None

        direction_str = sig.side
        bar_time = frame.index[idx]
        if _is_duplicate_signal(market.symbol, direction_str, bar_time):
            _rej("duplicate_signal")
            return None

        direction_raw = int(sig.direction)
        risk_factor = 0.5 if sig.regime == "HIGH_VOLATILITY" else 1.0

        account_tier = resolve_live_account_tier()
        if account_tier is None:
            from tradingbot.services.runtime_truth import entries_frozen

            if entries_frozen():
                logger.warning(
                    "MT5 equity unavailable — skipping adaptive signal (entries frozen)"
                )
                _rej("entries_frozen")
                return None
        sl, tp, extra = compute_sl_tp(
            df,
            direction_raw,
            VOL_REGIME_RULE_CONFIDENCE,
            symbol=market.symbol,
            strategy_name=sig.strategy_id.lower(),
            timeframe=market.timeframe,
            config=self._config,
            account_tier=account_tier,
        )

        logger.info(
            "Adaptive signal ready | %s %s regime=%s bar=%s atr=%.3f sl=%.2f tp=%.2f",
            sig.strategy_id,
            direction_str,
            sig.regime,
            df.index[-1],
            sig.atr_pct,
            float(sl or 0),
            float(tp or 0),
        )

        quality_extra: dict[str, Any] = {}
        if sig.quality_score is not None:
            quality_extra = {
                "quality_score": sig.quality_score,
                "score_components": sig.score_components or {},
                "quality_tier": sig.quality_tier,
            }

        signal = TradingSignal(
            direction=SignalDirection.BUY if direction_raw > 0 else SignalDirection.SELL,
            confidence=VOL_REGIME_RULE_CONFIDENCE,
            symbol=market.symbol,
            timeframe=market.timeframe,
            strategy_name=STRATEGY_ID,
            stop_loss=sl,
            take_profit=tp,
            metadata={
                "engine_id": STRATEGY_ID,
                "sub_strategy": sig.strategy_id,
                "regime": sig.regime,
                "atr_pct": round(sig.atr_pct, 4),
                "atr_sl_mult": sig.atr_sl_mult,
                "tp_rr": sig.tp_rr,
                "risk_factor": risk_factor,
                "risk_percent": round(self._risk_pct * risk_factor, 4),
                "ml_filter": "SKIP",
                "tq_skipped": True,
                "bar_timestamp": str(df.index[-1]),
                "account_tier": account_tier,
                **quality_extra,
                **extra,
            },
        )
        try:
            from tradingbot.services.engine_telemetry import ENGINE_ADAPTIVE, get_engine_telemetry

            get_engine_telemetry().record_signal(
                ENGINE_ADAPTIVE,
                symbol=market.symbol,
                timeframe=market.timeframe,
                direction=signal.direction.name,
                confidence=signal.confidence,
                strategy_name=STRATEGY_ID,
                bar_timestamp=str(df.index[-1]),
                extra={"regime": sig.regime, **quality_extra},
            )
        except Exception:
            pass
        return signal
