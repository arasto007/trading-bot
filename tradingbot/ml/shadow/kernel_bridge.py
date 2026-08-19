"""Phase 10 — observe ML signals against kernel strategy path and RiskGate (no orders)."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

import pandas as pd

from tradingbot.adapters.risk_gate import RiskGate, create_risk_gate
from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey, RiskDecision, TradingSignal
from tradingbot.ml.dataset.labels import compute_atr_at, compute_sl_tp
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker
from tradingbot.ml.shadow.shadow_signal import ShadowSignal

logger = logging.getLogger(__name__)


def _direction_enum(name: str) -> SignalDirection:
    upper = name.upper()
    if upper == "BUY":
        return SignalDirection.BUY
    if upper == "SELL":
        return SignalDirection.SELL
    return SignalDirection.HOLD


class ShadowKernelBridge:
    """
    Evaluate ML shadow signals against rule-based strategy output and RiskGate.

    Never invokes execution or order placement.
    """

    def __init__(
        self,
        *,
        legacy_config: dict[str, Any] | None = None,
        risk_gate: RiskGate | None = None,
        broker: PaperBroker | None = None,
    ) -> None:
        self._config = legacy_config or {}
        self._risk_gate = risk_gate or create_risk_gate(self._config)
        cfg = broker.config if broker else BrokerConfig()
        self._broker = broker or PaperBroker(cfg)
        self._registry = None

    def _get_strategy_registry(self):
        if self._registry is None:
            from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry

            self._registry = LegacyStrategyRegistry(self._config)
        return self._registry

    def observe_strategy_signal(
        self,
        market: MarketKey,
        candles: pd.DataFrame,
        *,
        correlation_data: dict | None = None,
    ) -> dict[str, Any]:
        """What the kernel signal stage (rule-based strategies) would emit."""
        try:
            registry = self._get_strategy_registry()
            signal = registry.generate_signal(market, candles, correlation_data)
        except Exception as exc:
            logger.warning("Strategy observation failed: %s", exc)
            return {
                "strategy_signal": "HOLD",
                "strategy_confidence": 0.0,
                "would_kernel_trade": False,
                "error": str(exc),
            }

        if signal is None:
            return {
                "strategy_signal": "HOLD",
                "strategy_confidence": 0.0,
                "would_kernel_trade": False,
            }

        return {
            "strategy_signal": signal.direction.name,
            "strategy_confidence": float(signal.confidence),
            "strategy_name": signal.strategy_name,
            "would_kernel_trade": signal.direction != SignalDirection.HOLD,
        }

    def build_trading_signal(
        self,
        shadow: ShadowSignal,
        candles: pd.DataFrame,
        bar_index: int,
    ) -> tuple[TradingSignal, float, float, float]:
        """Convert shadow ML signal to TradingSignal with virtual SL/TP."""
        direction = _direction_enum(shadow.direction)
        close = float(candles.iloc[bar_index]["close"])
        risk_unit = compute_atr_at(candles, bar_index)
        dir_int = 1 if direction == SignalDirection.BUY else -1 if direction == SignalDirection.SELL else 0
        fill = self._broker.execute_entry(close, dir_int)
        sl, tp = self._broker.sl_tp(fill.fill_price, dir_int, risk_unit)
        signal = TradingSignal(
            direction=direction,
            confidence=shadow.confidence,
            symbol=shadow.symbol,
            timeframe=shadow.timeframe,
            strategy_name="ml_shadow_phase9_9",
            stop_loss=sl,
            take_profit=tp,
            metadata={
                "entry": fill.fill_price,
                "probability": shadow.probability,
                "features_hash": shadow.features_hash,
                "shadow_only": True,
            },
        )
        return signal, fill.fill_price, sl, tp

    def evaluate_risk(
        self,
        signal: TradingSignal,
        candles: pd.DataFrame,
        *,
        bar_index: int,
        open_positions: list | None = None,
    ) -> RiskDecision:
        snapshot = {
            "ohlcv": candles.iloc[: bar_index + 1],
            "current_time": candles.index[bar_index],
            "open_positions": open_positions or [],
            "htf_bias": 0,
        }
        return self._risk_gate.evaluate(signal, snapshot)

    def evaluate(
        self,
        shadow: ShadowSignal,
        candles: pd.DataFrame,
        bar_index: int,
        *,
        open_positions: list | None = None,
        observe_strategy: bool = True,
    ) -> dict[str, Any]:
        """Full shadow evaluation: strategy observation + risk gate + virtual levels."""
        market = MarketKey(symbol=shadow.symbol, timeframe=shadow.timeframe)
        kernel_result = (
            self.observe_strategy_signal(market, candles.iloc[: bar_index + 1])
            if observe_strategy
            else {
                "strategy_signal": "HOLD",
                "strategy_confidence": 0.0,
                "would_kernel_trade": False,
                "observation_skipped": True,
            }
        )

        if not shadow.is_trade:
            return {
                "timestamp": shadow.timestamp,
                "symbol": shadow.symbol,
                "ml_signal": shadow.direction,
                "probability": shadow.probability,
                "kernel_result": kernel_result,
                "risk_result": {"allowed": False, "reason": "ml_hold"},
                "virtual_entry": None,
                "virtual_sl": None,
                "virtual_tp": None,
                "outcome": None,
                "aligned_with_kernel": kernel_result.get("strategy_signal") == shadow.direction,
            }

        trading_signal, entry, sl, tp = self.build_trading_signal(shadow, candles, bar_index)
        risk = self.evaluate_risk(trading_signal, candles, bar_index=bar_index, open_positions=open_positions)
        risk_payload = {
            "allowed": risk.allowed,
            "reason": risk.reason,
            "adjusted_lot": risk.adjusted_lot,
        }

        return {
            "timestamp": shadow.timestamp,
            "symbol": shadow.symbol,
            "ml_signal": shadow.direction,
            "probability": shadow.probability,
            "kernel_result": kernel_result,
            "risk_result": risk_payload,
            "virtual_entry": round(entry, 4),
            "virtual_sl": round(sl, 4),
            "virtual_tp": round(tp, 4),
            "virtual_lot": risk.adjusted_lot,
            "outcome": "pending" if risk.allowed else "blocked",
            "aligned_with_kernel": kernel_result.get("strategy_signal") == shadow.direction,
        }

    @staticmethod
    def risk_decision_to_dict(decision: RiskDecision) -> dict[str, Any]:
        return asdict(decision)
