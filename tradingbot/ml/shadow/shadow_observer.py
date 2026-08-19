"""Phase D — parallel PA / VOL / ML predictions (no orders)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.integration.config import is_ml_shadow_enabled
from tradingbot.ml.shadow.shadow_logger import record_shadow_cycle

logger = logging.getLogger(__name__)

_LAST_CYCLES: dict[str, dict[str, Any]] = {}


def _cycle_key(symbol: str, timeframe: str) -> str:
    return f"{symbol.upper()}:{timeframe}"


def get_last_shadow_cycle(symbol: str, timeframe: str) -> dict[str, Any] | None:
    return _LAST_CYCLES.get(_cycle_key(symbol, timeframe))


def extract_ml_fields(cycle: dict[str, Any]) -> tuple[str, float | None]:
    """Return (ml_direction, ml_probability) preferring ML kernel prediction."""
    kernel = cycle.get("ml_kernel_prediction") or {}
    phase = cycle.get("ml_prediction") or {}
    for src in (kernel, phase):
        d = str(src.get("direction", "HOLD")).upper()
        if d in ("BUY", "SELL"):
            prob = src.get("probability")
            if prob is None:
                prob = src.get("confidence")
            try:
                p = float(prob) if prob is not None else None
            except (TypeError, ValueError):
                p = None
            return d, p
    return "HOLD", None


def record_shadow_entry_from_cycle(
    *,
    ticket: int,
    symbol: str,
    timeframe: str,
    live_engine_direction: str,
    cycle: dict[str, Any] | None,
) -> None:
    from tradingbot.ml.shadow.shadow_logger import record_shadow_entry

    ml_dir, ml_prob = extract_ml_fields(cycle or {})
    record_shadow_entry(
        ticket=ticket,
        symbol=symbol,
        timeframe=timeframe,
        live_engine_direction=live_engine_direction,
        ml_prediction_direction=ml_dir,
        ml_probability=ml_prob,
        live_engine=str((cycle or {}).get("live_engine", "")),
    )


def _dir_name(raw: int | None) -> str:
    if raw == 1:
        return "BUY"
    if raw == -1:
        return "SELL"
    return "HOLD"


class ShadowObserver:
    """Probe rule + ML engines and log — never returns ML signals to kernel."""

    def __init__(self, legacy_config: dict[str, Any] | None = None, *, base_dir: str | None = None) -> None:
        self._config = dict(legacy_config or {})
        self._base_dir = base_dir or self._config.get("BASE_DIR")
        self._ml_adapter = None
        self._kernel_adapter = None
        self._legacy: Any = None
        self._vol_frame_cache: pd.DataFrame | None = None

    def _legacy_registry(self):
        if self._legacy is None:
            from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry

            self._legacy = LegacyStrategyRegistry(self._config)
        return self._legacy

    def _probe_pa(self, market: MarketKey, df: pd.DataFrame) -> str:
        try:
            sig = self._legacy_registry().generate_signal(market, df)
            if sig is None:
                return "HOLD"
            return sig.direction.name
        except Exception as exc:
            logger.debug("shadow PA probe failed: %s", exc)
            return "HOLD"

    def _probe_vol(self, df: pd.DataFrame) -> str:
        try:
            from tradingbot.strategies.vol_regime_signal import evaluate_at_index, prepare_frame

            frame = prepare_frame(df)
            if frame.empty:
                return "HOLD"
            sig = evaluate_at_index(frame, len(frame) - 1)
            if sig is None:
                return "HOLD"
            return sig.side
        except Exception as exc:
            logger.debug("shadow VOL probe failed: %s", exc)
            return "HOLD"

    def _probe_ml_phase99(self, market: MarketKey, df: pd.DataFrame) -> dict[str, Any]:
        try:
            if self._ml_adapter is None:
                from tradingbot.ml.shadow.ml_adapter import MLAdapter

                self._ml_adapter = MLAdapter.load(base_dir=self._base_dir)
            from tradingbot.ml.features.builder import FeatureBuilder

            builder = FeatureBuilder(market.symbol, self._base_dir)
            idx = len(df) - 1
            feats = builder.compute_at(df, idx)
            subset = {k: feats.get(k, 0.0) for k in self._ml_adapter.bundle.feature_order}
            ts = pd.Timestamp(df.index[idx]).isoformat()
            pred = self._ml_adapter.predict(subset, timestamp=ts)
            return {
                "source": "phase9_9",
                "direction": pred.direction,
                "probability": pred.probability,
                "confidence": pred.confidence,
            }
        except Exception as exc:
            return {"source": "phase9_9", "direction": "HOLD", "error": str(exc)}

    def _probe_ml_kernel(self, market: MarketKey, df: pd.DataFrame) -> dict[str, Any]:
        try:
            if self._kernel_adapter is None:
                from tradingbot.ml.integration.factory import build_kernel_adapter

                self._kernel_adapter = build_kernel_adapter(
                    base_dir=self._base_dir,
                    symbol=market.symbol.upper(),
                    enable_monitoring=False,
                )
            sig = self._kernel_adapter.generate_signal(market, df)
            if sig is None:
                return {"source": "ml_kernel", "direction": "HOLD"}
            meta = sig.metadata or {}
            return {
                "source": "ml_kernel",
                "direction": sig.direction.name,
                "probability": meta.get("ml_probability", meta.get("probability")),
                "confidence": float(sig.confidence or 0),
                "engine_id": meta.get("engine_id"),
            }
        except Exception as exc:
            return {"source": "ml_kernel", "direction": "HOLD", "error": str(exc)}

    def observe_cycle(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        *,
        live_signal: TradingSignal | None,
        inner_engine: str,
    ) -> None:
        if not is_ml_shadow_enabled():
            return
        if df is None or df.empty:
            return

        from tradingbot.domain.risk_logic import infer_regime_from_ohlcv

        regime = infer_regime_from_ohlcv(df)
        ts = str(df.index[-1])
        pa = self._probe_pa(market, df)
        vol = self._probe_vol(df)
        ml_pred = self._probe_ml_phase99(market, df)
        kernel_pred = self._probe_ml_kernel(market, df)

        payload = {
            "timestamp": ts,
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "regime": regime,
            "pa_signal": pa,
            "vol_signal": vol,
            "ml_prediction": ml_pred,
            "ml_kernel_prediction": kernel_pred,
            "live_engine": inner_engine,
            "live_signal": live_signal.direction.name if live_signal else "HOLD",
            "live_strategy": live_signal.strategy_name if live_signal else "",
            "final_trade_result": None,
        }
        _LAST_CYCLES[_cycle_key(market.symbol, market.timeframe)] = payload
        record_shadow_cycle(payload)
