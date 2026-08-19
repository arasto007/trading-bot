"""Paper trading engine — offline long-horizon simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.labels import compute_atr_at
from tradingbot.ml.memory.schema import DecisionRecord, session_from_features
from tradingbot.ml.paper._types import PaperConfig, SignalMode
from tradingbot.ml.paper.broker_sim import BrokerSim
from tradingbot.ml.paper.metrics import compute_metrics, session_breakdown, slippage_impact
from tradingbot.ml.paper.portfolio import Portfolio
from tradingbot.ml.paper.trade_executor import TradeExecutor


@dataclass
class PaperTradingEngine:
    """
    Offline paper trading simulation.

    Processes chronological decision points against candle history.
    No MT5, no live orders.
    """

    config: PaperConfig | None = None
    signal_mode: SignalMode = SignalMode.HYBRID
    broker: BrokerSim | None = None
    executor: TradeExecutor | None = None

    def __post_init__(self) -> None:
        self.config = self.config or PaperConfig()
        self.broker = self.broker or BrokerSim(
            deterministic=self.config.deterministic,
            seed=self.config.random_seed,
        )
        self.executor = self.executor or TradeExecutor(self.config)

    def run(
        self,
        candles: pd.DataFrame,
        decisions: list[DecisionRecord],
        *,
        bar_offset: int = 0,
        one_trade_at_a_time: bool = True,
    ) -> dict[str, Any]:
        portfolio = Portfolio(
            initial_balance_r=self.config.initial_balance_r,
            compounding=self.config.compounding,
        )
        candles = self._prepare_candles(candles)
        ordered = sorted(decisions, key=lambda d: d.timestamp)
        executor = self.executor
        assert executor is not None
        broker = self.broker
        assert broker is not None

        used_indices: set[int] = set()

        for record in ordered:
            idx = self._match_index(candles, record.timestamp)
            if idx is None or idx in used_indices:
                continue
            if one_trade_at_a_time and portfolio.open_trades:
                continue

            signal, direction = executor.resolve_signal(record, self.signal_mode)
            if direction == 0:
                continue

            feats = record.features_snapshot or {}
            session = record.session if record.session != "unknown" else session_from_features(feats)
            vol = float(feats.get("volatility_regime", 0.5))
            news = float(feats.get("spread_spike", 0)) >= 0.5
            mid = float(record.entry_price or candles["close"].iloc[idx])

            sim = broker.simulate_entry(
                mid,
                direction,
                session=session,
                volatility_regime=vol,
                news_event=news,
            )
            if not sim.get("accepted"):
                continue

            entry_idx = min(idx + int(sim.get("delay_bars", 0)), len(candles) - 1)
            risk_unit = compute_atr_at(candles, entry_idx, self.config.atr_period)

            trade = executor.open_trade(
                timestamp=str(record.timestamp),
                symbol=record.symbol,
                direction=direction,
                entry_price=float(sim["entry_price"]),
                signal_source=self.signal_mode.value,
                session=session,
                slippage=float(sim.get("slippage", 0)),
                spread_cost=float(sim.get("spread_cost", 0)),
                risk_unit=risk_unit,
            )
            portfolio.add_open(trade)
            resolved = executor.resolve_trade_on_candles(trade, candles, entry_idx)
            resolved.exit_timestamp = str(record.timestamp)
            portfolio.close_trade(resolved)
            used_indices.add(idx)

        metrics = compute_metrics(portfolio)
        return {
            "portfolio": portfolio,
            "metrics": metrics.to_dict(),
            "equity_curve": portfolio.equity_curve,
            "closed_trades": [t.to_dict() for t in portfolio.closed_trades],
            "session_breakdown": session_breakdown(portfolio),
            "slippage_impact": slippage_impact(portfolio),
            "signal_mode": self.signal_mode.value,
            "bar_offset": bar_offset,
        }

    def compare_modes(
        self,
        candles: pd.DataFrame,
        decisions: list[DecisionRecord],
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for mode in (SignalMode.RULE, SignalMode.ML, SignalMode.HYBRID):
            engine = PaperTradingEngine(config=self.config, signal_mode=mode)
            out[mode.value] = engine.run(candles, decisions)["metrics"]
        return out

    @staticmethod
    def _prepare_candles(candles: pd.DataFrame) -> pd.DataFrame:
        df = candles.copy().reset_index(drop=True)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    @staticmethod
    def _match_index(candles: pd.DataFrame, timestamp: str) -> int | None:
        if candles.empty:
            return None
        target = pd.to_datetime(timestamp, utc=True)
        if "timestamp" in candles.columns:
            ts = pd.to_datetime(candles["timestamp"], utc=True)
            pos = int(ts.searchsorted(target, side="right")) - 1
            return max(0, min(pos, len(candles) - 1))
        if isinstance(candles.index, pd.DatetimeIndex):
            pos = int(candles.index.searchsorted(target, side="right")) - 1
            return max(0, min(pos, len(candles) - 1))
        return 0
