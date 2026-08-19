"""Phase 10.1 — ML strategy adapter (IStrategyRegistry-compatible)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, TradingSignal
from tradingbot.ml.dataset.labels import compute_atr_at
from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.integration.config import is_ml_shadow_enabled
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime
from tradingbot.ml.shadow.ml_adapter import MLAdapter
from tradingbot.ports.strategies import IStrategyRegistry

logger = logging.getLogger(__name__)
STRATEGY_NAME = "ml_shadow_phase9_9"


class MLShadowStrategy:
    """Produce TradingSignal from Phase 9.9 model — kernel-compatible."""

    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        seed: int = 42,
        broker: PaperBroker | None = None,
    ) -> None:
        self.base_dir = base_dir
        self._broker = broker or PaperBroker(BrokerConfig())
        self._adapter: MLAdapter | None = None
        self._builder: FeatureBuilder | None = None
        self._seed = seed
        self._regime = "RANGE"

    def _ensure_loaded(self, symbol: str) -> None:
        if self._adapter is None:
            self._adapter = MLAdapter.load(base_dir=self.base_dir, seed=self._seed)
            self._regime = self._adapter.bundle.config.get("regime", "RANGE")
        if self._builder is None:
            self._builder = FeatureBuilder(symbol, self.base_dir)

    def generate_signal(
        self,
        market: MarketKey,
        df: pd.DataFrame,
        correlation_data: dict | None = None,
    ) -> TradingSignal | None:
        if not is_ml_shadow_enabled():
            return None
        if df is None or df.empty or len(df) < 60:
            return None

        self._ensure_loaded(market.symbol)
        assert self._adapter is not None and self._builder is not None

        index = len(df) - 1
        feats = self._builder.compute_at(df, index)
        regime_row = pd.Series(feats)
        if assign_market_regime(pd.DataFrame([regime_row])).iloc[0] != self._regime:
            return None

        subset = {k: feats.get(k, 0.0) for k in self._adapter.bundle.feature_order}
        ts = pd.Timestamp(df.index[index]).isoformat()
        prediction = self._adapter.predict(subset, timestamp=ts)
        direction_name = prediction.direction

        if direction_name == "HOLD":
            return None

        direction = SignalDirection.BUY if direction_name == "BUY" else SignalDirection.SELL
        close = float(df["close"].iloc[index])
        dir_int = 1 if direction == SignalDirection.BUY else -1
        risk_unit = compute_atr_at(df, index)
        fill = self._broker.execute_entry(close, dir_int)
        sl, tp = self._broker.sl_tp(fill.fill_price, dir_int, risk_unit)

        return TradingSignal(
            direction=direction,
            confidence=prediction.confidence,
            symbol=market.symbol,
            timeframe=market.timeframe,
            strategy_name=STRATEGY_NAME,
            stop_loss=sl,
            take_profit=tp,
            metadata={
                "ml_probability": prediction.probability,
                "features_hash": prediction.features_hash,
                "signal_source": "ml_shadow",
                "entry": fill.fill_price,
                "bar_timestamp": ts,
                "shadow_only": True,
            },
        )


class MLShadowStrategyRegistry(MLShadowStrategy):
    """Alias implementing IStrategyRegistry protocol."""
