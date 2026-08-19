"""Phase 15D — shadow mode replay (dual-path, no execution)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd

from tradingbot.adapters.legacy_strategy_registry import LegacyStrategyRegistry
from tradingbot.adapters.risk_gate import create_risk_gate
from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
from tradingbot.ml.integration.pipeline_cache import PipelineCache
from tradingbot.ml.live_validation.config import (
    DEFAULT_STRIDE,
    DEFAULT_WARMUP_BARS,
    EXPECTED_DATASET_FINGERPRINT,
    HEALTH_EVERY_N_BARS,
)
from tradingbot.ml.live_validation.decision_compare import DecisionComparer
from tradingbot.ml.live_validation.latency_monitor import ShadowLatencyMonitor
from tradingbot.ml.live_validation.live_health import LiveHealthMonitor
from tradingbot.ml.live_validation.risk_compare import RiskComparer
from tradingbot.ml.live_validation.shadow_equity import ShadowEquityTracker
from tradingbot.ml.live_validation.shadow_statistics import ShadowStatistics
from tradingbot.ml.live_validation.shadow_trade import shadow_trade_from_signal
from tradingbot.ml.live_validation.signal_consistency import SignalConsistencyValidator
from tradingbot.ml.phase15a.trend_bundle import validate_trend_checksum
from tradingbot.ml.research.phase14_7.trade_tracker import simulate_outcome

logger = logging.getLogger(__name__)

# Safety: shadow mode never invokes real execution.
ORDER_SEND_CALLS = 0


def _filter_days(candles: pd.DataFrame, days: int) -> pd.DataFrame:
    if candles.empty:
        return candles
    end = candles.index.max()
    start = end - timedelta(days=days)
    return candles[candles.index >= start]


def _portfolio_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "ohlcv": df,
        "open_positions": [],
        "spread_pips": 1.0,
        "balance": 10_000.0,
        "equity": 10_000.0,
    }


def _apply_simulated_pnl(trade: Any, candles: pd.DataFrame, bar_idx: int, risk_amount: float) -> None:
    direction = trade.signal
    if direction not in ("BUY", "SELL"):
        return
    outcome = simulate_outcome(candles, bar_idx, direction)
    r_mult = float(outcome.get("r_multiple", 0.0))
    trade.duration_bars = int(outcome.get("duration_bars", 0)) if "duration_bars" in outcome else 0
    entry = trade.entry
    if entry is None:
        entry = float(candles.iloc[bar_idx]["close"])
        trade.entry = entry
    sl = trade.sl
    if sl is None and entry:
        atr = float(candles.iloc[bar_idx]["high"] - candles.iloc[bar_idx]["low"])
        sl_dist = max(atr, entry * 0.0005)
        sl = entry - sl_dist if direction == "BUY" else entry + sl_dist
        trade.sl = sl
    if entry and sl:
        risk_dist = abs(entry - sl)
        if risk_dist > 0:
            move = r_mult * risk_dist
            trade.exit = entry + move if direction == "BUY" else entry - move
    trade.pnl = r_mult * risk_amount


@dataclass
class ShadowModeResult:
    stats: ShadowStatistics = field(default_factory=ShadowStatistics)
    equity: ShadowEquityTracker = field(default_factory=ShadowEquityTracker)
    latency: ShadowLatencyMonitor = field(default_factory=ShadowLatencyMonitor)
    health: LiveHealthMonitor = field(default_factory=LiveHealthMonitor)
    consistency: SignalConsistencyValidator = field(default_factory=SignalConsistencyValidator)
    checksum_before: dict[str, Any] = field(default_factory=dict)
    checksum_after: dict[str, Any] = field(default_factory=dict)
    checksum_stable: bool = True
    order_send_calls: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stats": self.stats.build_report(),
            "equity": self.equity.build_report(self.stats.shadow_trades),
            "latency": self.latency.build_report(),
            "health": self.health.build_report(),
            "consistency": self.consistency.summary(),
            "checksum_stable": self.checksum_stable,
            "order_send_calls": self.order_send_calls,
            "errors": self.errors[:20],
        }


@dataclass
class ShadowModeRunner:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    days: int = 180
    seed: int = 42
    base_dir: str | None = None
    stride: int = DEFAULT_STRIDE
    warmup: int = DEFAULT_WARMUP_BARS
    legacy_config: dict[str, Any] | None = None
    risk_per_trade: float = 100.0

    def run(self) -> ShadowModeResult:
        global ORDER_SEND_CALLS
        ORDER_SEND_CALLS = 0
        PipelineCache.reset()
        result = ShadowModeResult()
        result.order_send_calls = ORDER_SEND_CALLS

        candles = CandleStore(self.base_dir).load(self.symbol, self.timeframe)
        if candles is None or candles.empty:
            result.errors.append("candles_unavailable")
            return result

        window = _filter_days(candles, self.days)
        full_candles = candles
        market = MarketKey(self.symbol, self.timeframe)
        cfg = dict(self.legacy_config or {})
        if self.base_dir:
            cfg["BASE_DIR"] = self.base_dir

        stack = build_ml_kernel_stack(base_dir=self.base_dir, symbol=self.symbol)
        adapter = build_kernel_adapter(
            base_dir=self.base_dir, symbol=self.symbol, stack=stack, enable_monitoring=False,
        )
        legacy = LegacyStrategyRegistry(cfg)
        risk_gate = create_risk_gate(cfg)
        equity = ShadowEquityTracker(risk_per_trade=self.risk_per_trade)
        stats = ShadowStatistics()
        latency = ShadowLatencyMonitor()
        health = LiveHealthMonitor()
        consistency = SignalConsistencyValidator()

        result.checksum_before = validate_trend_checksum(base_dir=self.base_dir)
        health.run_bundle_check(self.base_dir)
        health.run_registry_check(self.base_dir)
        health.run_fingerprint_check(
            EXPECTED_DATASET_FINGERPRINT,
            symbol=self.symbol,
            timeframe=self.timeframe,
            base_dir=self.base_dir,
        )

        if len(window) > self.warmup:
            try:
                warm_idx = full_candles.index.get_loc(window.index[self.warmup])
                warm_slice = full_candles.iloc[max(0, warm_idx - self.warmup) : warm_idx + 1].copy()
                adapter.generate_signal(market, warm_slice, config=cfg)
            except Exception as exc:
                result.errors.append(f"warmup:{exc}")

        indices = list(range(self.warmup, len(window), self.stride))
        replay_cache: dict[str, Any] = {}

        for bar_num, i in enumerate(indices):
            bar_ts = window.index[i]
            full_idx = full_candles.index.get_loc(bar_ts)
            slice_df = full_candles.iloc[max(0, full_idx - self.warmup) : full_idx + 1]
            ts = str(bar_ts)
            stats.bars_processed += 1

            legacy_signal = None
            try:
                legacy_signal = legacy.generate_signal(market, slice_df.copy())
                if legacy_signal is not None:
                    stats.legacy_signals += 1
            except Exception as exc:
                if bar_num == 0:
                    result.errors.append(f"legacy:{exc}")

            ml_signal = None
            ml_unified = None
            try:
                ml_signal = adapter.generate_signal(market, slice_df.copy(), config=cfg)
                ml_unified = adapter.last_unified_signal
                lat = adapter.last_latency.to_dict()
                latency.record_breakdown(lat)
                if ml_unified is not None:
                    check = consistency.record(
                        timestamp=ts, unified=ml_unified, trading_signal=ml_signal,
                    )
                    if ts in replay_cache:
                        consistency.verify_replay(replay_cache[ts], check)
                    else:
                        replay_cache[ts] = check

                if ml_unified is not None and ml_unified.direction in ("BUY", "SELL"):
                    stats.ml_signals += 1
            except Exception as exc:
                result.errors.append(f"ml@{ts}:{exc}")
                health.record_exception(exc)

            stats.decision_comparer.compare(
                timestamp=ts,
                legacy_signal=legacy_signal,
                ml_signal=ml_signal,
                ml_unified=ml_unified,
            )

            risk_decision = None
            if ml_unified is not None and ml_unified.direction in ("BUY", "SELL") and ml_signal is not None:
                snapshot = _portfolio_snapshot(slice_df)
                risk_decision = risk_gate.evaluate(ml_signal, snapshot)
                stats.risk_comparer.compare(
                    timestamp=ts,
                    legacy_signal=legacy_signal,
                    ml_signal=ml_signal,
                    risk_decision=risk_decision,
                    ml_unified=ml_unified,
                )
                entry = float(slice_df.iloc[-1]["close"])
                trade = shadow_trade_from_signal(
                    ml_signal,
                    unified=ml_unified,
                    entry=entry,
                    risk_allowed=bool(risk_decision.allowed),
                    risk_reason=str(risk_decision.reason),
                    bar_time=ts,
                )
                if risk_decision.allowed:
                    _apply_simulated_pnl(trade, full_candles, full_idx, self.risk_per_trade)
                    equity.apply_trade(trade)
                stats.add_trade(trade)
                stats.orders_blocked += 1

            if bar_num % HEALTH_EVERY_N_BARS == 0:
                health.run_bundle_check(self.base_dir)
                health.update_latency(latency.passes_targets())
                health.update_feature_consistency(consistency.is_deterministic())

        result.checksum_after = validate_trend_checksum(base_dir=self.base_dir)
        result.checksum_stable = (
            result.checksum_before.get("valid") == result.checksum_after.get("valid")
            and result.checksum_before.get("bundle_sha256") == result.checksum_after.get("bundle_sha256")
        )
        health.update_latency(latency.passes_targets())
        health.update_feature_consistency(consistency.is_deterministic())
        result.stats = stats
        result.equity = equity
        result.latency = latency
        result.health = health
        result.consistency = consistency
        result.order_send_calls = ORDER_SEND_CALLS
        return result
