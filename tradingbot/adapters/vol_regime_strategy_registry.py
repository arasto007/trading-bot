"""VOL_REGIME strategy registry — full live kernel path (no ML, no demo caps)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.timeframes import to_kernel
from tradingbot.config.live import get_live_config
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.domain.signal_helpers import compute_sl_tp
from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE
from tradingbot.ml.research.live_l3.execution_validation import (
    _infer_regime,
    _session_from_row,
    _spread_pips,
)
from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics, RiskRecommendation
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_types import TradeQualityContext
from tradingbot.ml.trade_quality.regime_quality import VOL_REGIME_ENGINE
from tradingbot.ports.strategies import IStrategyRegistry
from tradingbot.strategies.vol_regime_signal import (
    CONFIG_ID,
    DEFAULT_ATR_SL_MULT,
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    DEFAULT_TP_RR,
    STRATEGY_ID,
    evaluate_at_index,
    prepare_frame,
)

logger = logging.getLogger(__name__)


class VolRegimeStrategyRegistry(IStrategyRegistry):
    """Production VOL_REGIME signals for TradingKernel — any MT5 account."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or load_legacy_config())
        live = get_live_config()
        self._enabled = bool(live.get("VOL_REGIME_ENABLED", True))
        self._skip_tq = bool(live.get("VOL_REGIME_SKIP_TQ", True))
        self._quality = TradeQualityEngine(history=HistoricalMetrics())
        self._risk_pct = float(
            live.get("VOL_REGIME_RISK_PER_TRADE_PCT")
            or self._config.get("RISK_PER_TRADE", 0.005) * 100
            or 1.0
        )
        logger.info(
            "VolRegimeStrategyRegistry active | config=%s rr=%s ml=SKIP tq=%s",
            CONFIG_ID,
            DEFAULT_TP_RR,
            "SKIP" if self._skip_tq else "ON",
        )

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        def _rej(reason: str) -> None:
            try:
                from tradingbot.services.engine_telemetry import ENGINE_VOL, get_engine_telemetry

                get_engine_telemetry().record_rejection(
                    ENGINE_VOL,
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
        if market.symbol.upper() != DEFAULT_SYMBOL or kernel_tf != DEFAULT_TIMEFRAME:
            _rej("wrong_symbol_or_timeframe")
            return None

        frame = prepare_frame(df)
        if frame.empty:
            _rej("empty_frame")
            return None

        idx = len(frame) - 1
        sig = evaluate_at_index(frame, idx)
        if sig is None:
            row = frame.iloc[idx]
            atr = float(row.get("atr_pct", float("nan")))
            in_band = bool(atr == atr and 0.30 <= atr <= 0.70)
            logger.info(
                "VOL_REGIME no setup | bar=%s atr_pct=%.3f in_band=%s",
                frame.index[idx],
                atr,
                in_band,
            )
            _rej("no_setup")
            return None

        direction_raw = int(sig.direction)
        direction_str = "BUY" if direction_raw > 0 else "SELL"
        row = frame.iloc[idx]

        risk = RiskRecommendation(
            allowed=True,
            risk_percent=self._risk_pct,
            multiplier=1.0,
            confidence_factor=1.0,
            regime_factor=1.0,
            volatility_factor=1.0,
            session_factor=1.0,
            drawdown_factor=1.0,
            reason="vol_regime live kernel",
            trace=["VolRegimeStrategyRegistry"],
        )
        ctx = TradeQualityContext(
            market=None,  # type: ignore[arg-type]
            calibrated=None,  # type: ignore[arg-type]
            risk=risk,
            engine=VOL_REGIME_ENGINE,
            regime=_infer_regime(row),
            action=direction_str,
            confidence=VOL_REGIME_RULE_CONFIDENCE,
            risk_percent=self._risk_pct,
            atr_percentile=float(sig.atr_pct),
            spread_pips=_spread_pips(row),
            spread_class="NORMAL",
            session=_session_from_row(row),
            rr_ratio=DEFAULT_TP_RR,
        )
        if self._skip_tq:
            quality = None
        else:
            quality = self._quality.evaluate(ctx)
            if not quality.allowed:
                logger.info(
                    "VOL_REGIME signal blocked by TQ | %s score=%.3f blocked_by=%s",
                    direction_str,
                    quality.score,
                    quality.blocked_by or quality.reason,
                )
                _rej(f"trade_quality_blocked:{quality.blocked_by or quality.reason}")
                return None

        sl, tp, extra = compute_sl_tp(
            df,
            direction_raw,
            VOL_REGIME_RULE_CONFIDENCE,
            symbol=market.symbol,
            strategy_name="vol_regime",
            timeframe=market.timeframe,
            config=self._config,
        )

        logger.info(
            "VOL_REGIME signal ready | %s bar=%s atr_pct=%.3f sl=%.2f tp=%.2f",
            direction_str,
            df.index[-1],
            float(sig.atr_pct),
            float(sl or 0),
            float(tp or 0),
        )

        signal = TradingSignal(
            direction=SignalDirection.BUY if direction_raw > 0 else SignalDirection.SELL,
            confidence=VOL_REGIME_RULE_CONFIDENCE,
            symbol=market.symbol,
            timeframe=market.timeframe,
            strategy_name=STRATEGY_ID,
            stop_loss=sl,
            take_profit=tp,
            metadata={
                "config_id": CONFIG_ID,
                "engine_id": VOL_REGIME_ENGINE,
                "atr_sl_mult": DEFAULT_ATR_SL_MULT,
                "tp_rr": DEFAULT_TP_RR,
                "ml_filter": "SKIP",
                "tq_score": quality.score if quality else None,
                "tq_skipped": self._skip_tq,
                "bar_timestamp": str(df.index[-1]),
                **extra,
            },
        )
        try:
            from tradingbot.services.engine_telemetry import ENGINE_VOL, get_engine_telemetry

            get_engine_telemetry().record_signal(
                ENGINE_VOL,
                symbol=market.symbol,
                timeframe=market.timeframe,
                direction=signal.direction.name,
                confidence=signal.confidence,
                strategy_name=STRATEGY_ID,
                bar_timestamp=str(df.index[-1]),
            )
        except Exception:
            pass
        return signal
