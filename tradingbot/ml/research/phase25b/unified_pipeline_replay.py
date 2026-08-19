"""Full production TradingKernel pipeline replay for research/paper parity."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import MarketKey
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.accounting.engine import AccountingEngine
from tradingbot.ml.research.phase25b.parity_replay_adapter import ParityReplayMarketDataAdapter
from tradingbot.ml.research.phase25b.replay_portfolio import ReplayPortfolioTracker
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

LOOKBACK_BARS = 300
MIN_KERNEL_BARS = 250
DEFAULT_WARMUP = max(MIN_KERNEL_BARS, LOOKBACK_BARS // 2)


@dataclass
class ReplayConfig:
    base_dir: str | None = None
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    tail_only: int | None = 400
    days: int | None = None
    stride: int = 1
    warmup_bars: int = DEFAULT_WARMUP
    use_forming_bar_adapter: bool = True
    exit_mode: str = "CURRENT"


class _Mt5MockContext:
    """Stub MT5 reads for offline RiskGate + Execution paper branch."""

    def __enter__(self) -> _Mt5MockContext:
        from unittest import mock

        self._patches = [
            mock.patch(
                "tradingbot.adapters.risk_gate.RiskGate._sync_mt5_account",
                return_value=None,
            ),
            mock.patch(
                "tradingbot.services.live_risk_tracker.LiveRiskTracker.sync_from_mt5",
                return_value=None,
            ),
            mock.patch(
                "tradingbot.adapters.risk_gate.RiskGate._live_spread_pips",
                return_value=1.0,
            ),
            mock.patch(
                "tradingbot.adapters.mt5_health.check_autotrading_ready",
                return_value=(True, "mock ok"),
            ),
            mock.patch(
                "tradingbot.adapters.mt5_execution.ensure_mt5_connected",
                return_value=True,
            ),
            mock.patch(
                "tradingbot.adapters.mt5_execution._current_price",
                return_value=2000.0,
            ),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *args: object) -> None:
        for patch in self._patches:
            patch.stop()


def _closed_bar_timestamp(enriched: pd.DataFrame | None) -> str | None:
    if enriched is None or enriched.empty:
        return None
    closed = exclude_forming_bar(enriched)
    if closed is None or closed.empty:
        return None
    return pd.to_datetime(closed.index[-1], utc=True).isoformat()


def _record_from_context(
    ctx: Any,
    *,
    adapter: Any,
    registry: Any,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    unified = getattr(adapter, "last_unified_signal", None) if adapter is not None else None
    filt_diag = getattr(adapter, "last_filter_diagnostics", None)
    latency = getattr(adapter, "last_latency", None)

    decision = "HOLD"
    confidence = 0.0
    regime = None
    engine = None
    checksum = None
    quality_score = None
    risk_percent = None
    sl = tp = lot = None

    if unified is not None:
        decision = str(unified.direction)
        confidence = float(unified.confidence)
        regime = unified.regime
        engine = unified.engine
        checksum = unified.checksum
        quality_score = float(unified.quality)
        risk_percent = float(unified.risk)
        sl = unified.sl
        tp = unified.tp

    signal = ctx.signal
    if signal is not None:
        decision = signal.direction.name
        confidence = float(signal.confidence)
        sl = signal.stop_loss if signal.stop_loss is not None else sl
        tp = signal.take_profit if signal.take_profit is not None else tp
        lot = signal.lot_size
        meta = signal.metadata or {}
        regime = meta.get("regime", regime)
        engine = meta.get("engine_name", engine)
        checksum = meta.get("unified_checksum", checksum)
        quality_score = meta.get("quality", quality_score)
        risk_percent = meta.get("risk_percent", risk_percent)

    ts = _closed_bar_timestamp(ctx.enriched_ohlcv)

    risk_allowed = None
    risk_reason = ""
    if ctx.risk is not None:
        risk_allowed = bool(ctx.risk.allowed)
        risk_reason = str(ctx.risk.reason or "")
        if ctx.risk.adjusted_lot is not None:
            lot = ctx.risk.adjusted_lot

    exec_message = ""
    exec_success = None
    if ctx.execution is not None:
        exec_message = str(ctx.execution.message or "")
        exec_success = bool(ctx.execution.success)

    return {
        "timestamp": ts,
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": regime,
        "engine": engine,
        "feature_vector_checksum": checksum,
        "confidence": confidence,
        "quality_score": quality_score,
        "risk_percent": risk_percent,
        "decision": decision,
        "risk_allowed": risk_allowed,
        "risk_reason": risk_reason,
        "filter_diagnostics": filt_diag.to_dict() if filt_diag is not None else {},
        "sl": sl,
        "tp": tp,
        "volume": lot,
        "execution_message": exec_message,
        "execution_success": exec_success,
        "registry_source": getattr(registry, "last_source", None),
        "pipeline_errors": list(ctx.errors),
        "latency_ms": latency.to_dict() if latency is not None else {},
    }


def _build_kernel(replay: ParityReplayMarketDataAdapter, legacy_config: dict[str, Any]) -> tuple[Any, Any, Any]:
    from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
    from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter
    from tradingbot.adapters.risk_gate import create_risk_gate
    from tradingbot.config.settings import KernelSettings
    from tradingbot.kernel.trading_kernel import TradingKernel
    from tradingbot.ml.integration.factory import build_strategy_registry

    base_dir = legacy_config.get("BASE_DIR", ".")
    settings = KernelSettings(
        base_dir=legacy_config.get("BASE_DIR", "."),
        symbols=[legacy_config.get("SYMBOL", "XAUUSD")],
        timeframes=[legacy_config.get("TIMEFRAME", "M5")],
        cycle_interval_seconds=60.0,
        initial_balance=float(legacy_config.get("initial_balance", 10_000)),
        extra=legacy_config,
    )
    registry = build_strategy_registry(legacy_config, base_dir=base_dir, symbol=settings.symbols[0])
    kernel = TradingKernel(
        settings=settings,
        market_data=replay,
        indicators=TechnicalIndicatorEngine(legacy_config),
        strategies=registry,
        risk=create_risk_gate(legacy_config),
        executor=Mt5ExecutionAdapter(legacy_config),
        position_manager=None,
    )
    return kernel, registry, settings


async def _run_replay_async(
    *,
    window: pd.DataFrame,
    config: ReplayConfig,
    legacy_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    os.environ["TRADINGBOT_PAPER"] = "1"
    os.environ.pop("TRADINGBOT_DRY_RUN", None)
    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"

    PipelineCache.reset()
    if config.use_forming_bar_adapter:
        replay = ParityReplayMarketDataAdapter(window, timeframe=config.timeframe)
    else:
        from tradingbot.ml.integration.replay_market_data import ReplayMarketDataAdapter

        replay = ReplayMarketDataAdapter(window)

    kernel, registry, settings = _build_kernel(replay, legacy_config)
    adapter = getattr(registry, "_adapter", None)
    market = MarketKey(config.symbol, config.timeframe)
    initial_balance = float(legacy_config.get("initial_balance", 10_000))
    portfolio = {
        "balance": initial_balance,
        "equity": initial_balance,
        "open_positions": [],
        "correlation_data": {},
        "htf_bias_map": {},
        "htf_bias": 0,
    }
    accounting = AccountingEngine(initial_balance=initial_balance, symbol=config.symbol)
    portfolio_tracker = ReplayPortfolioTracker(
        window, symbol=config.symbol, accounting=accounting, exit_mode=config.exit_mode
    )

    warmup = min(config.warmup_bars, max(0, len(window) - 2))
    indices = list(range(warmup, len(window), max(1, config.stride)))
    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "mode": "unified_pipeline_replay",
        "pipeline_stages": kernel.pipeline_stages,
        "forming_bar_adapter": config.use_forming_bar_adapter,
        "lookback_bars": LOOKBACK_BARS,
        "bars_evaluated": 0,
        "warmup_bars": warmup,
        "stride": config.stride,
    }

    with _Mt5MockContext():
        for bar_index in indices:
            replay.set_bar_index(bar_index)
            portfolio_tracker.advance_to_bar(bar_index)
            portfolio_tracker.sync_portfolio(portfolio)
            ctx = await kernel.run_market_cycle(market, portfolio)
            meta["bars_evaluated"] += 1
            record = _record_from_context(
                ctx,
                adapter=adapter,
                registry=registry,
                symbol=config.symbol,
                timeframe=config.timeframe,
            )
            record["bar_index"] = bar_index
            record["replay_open_positions"] = len(portfolio.get("open_positions", []))
            records.append(record)

            if ctx.signal is not None and ctx.signal.direction not in (SignalDirection.HOLD,):
                if ctx.execution is not None and ctx.execution.success:
                    entry_ts = record.get("timestamp") or pd.to_datetime(
                        window.index[bar_index], utc=True
                    ).isoformat()
                    entry_price = float(window.iloc[bar_index]["close"])
                    risk_pct = float(record.get("risk_percent") or 0.3)
                    sizing = accounting.resolve_lot(
                        configured_risk_percent=risk_pct,
                        entry_price=entry_price,
                        stop_loss=ctx.signal.stop_loss,
                    )
                    portfolio_tracker.open_from_execution(
                        bar_index=bar_index,
                        entry_timestamp=str(entry_ts),
                        direction=ctx.signal.direction.name,
                        entry_price=entry_price,
                        sl=ctx.signal.stop_loss,
                        tp=ctx.signal.take_profit,
                        lot=sizing.executed_lot,
                        regime=str(record.get("regime") or ""),
                        engine=str(record.get("engine") or ""),
                        confidence=float(record.get("confidence") or 0),
                        risk_percent=risk_pct,
                        sizing=sizing.to_dict(),
                    )
                    record["volume"] = sizing.executed_lot
                    record["sizing"] = sizing.to_dict()
                    portfolio_tracker.sync_portfolio(portfolio)

    meta["replay_portfolio"] = portfolio_tracker.export_summary()
    meta["accounting"] = accounting.export()
    meta["closed_trades"] = portfolio_tracker.export_closed_trades()
    meta["portfolio_timeline_bars"] = len(portfolio_tracker.timeline)
    meta["position_lifecycle_events"] = len(portfolio_tracker.lifecycle)
    meta["portfolio_timeline"] = portfolio_tracker.timeline
    meta["position_lifecycle"] = portfolio_tracker.lifecycle
    return records, meta


def _load_window(config: ReplayConfig) -> pd.DataFrame:
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles

    candles_raw = CandleStore(config.base_dir).load(config.symbol, config.timeframe)
    if candles_raw is None or candles_raw.empty:
        return pd.DataFrame()

    if config.tail_only is not None:
        return normalize_candles_for_builder(candles_raw).tail(config.tail_only).copy()
    if config.days is not None:
        return prepare_calibration_candles(candles_raw, days=int(config.days))
    return normalize_candles_for_builder(candles_raw).copy()


def run_unified_pipeline_replay(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    tail_only: int | None = 400,
    days: int | None = None,
    stride: int = 1,
    warmup_bars: int = DEFAULT_WARMUP,
    use_forming_bar_adapter: bool = True,
    legacy_config: dict[str, Any] | None = None,
    exit_mode: str = "CURRENT",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Run production TradingKernel pipeline bar-by-bar on frozen candles.

    This is the canonical repaired research path — identical depth to ``--paper``.
    """
    from tradingbot.adapters.legacy_loader import load_legacy_config

    cfg = dict(legacy_config or load_legacy_config())
    if base_dir:
        cfg["BASE_DIR"] = base_dir
    cfg["SYMBOL"] = symbol
    cfg["TIMEFRAME"] = timeframe

    replay_config = ReplayConfig(
        base_dir=cfg.get("BASE_DIR"),
        symbol=symbol,
        timeframe=timeframe,
        tail_only=tail_only,
        days=days,
        stride=stride,
        warmup_bars=warmup_bars,
        use_forming_bar_adapter=use_forming_bar_adapter,
        exit_mode=exit_mode,
    )
    window = _load_window(replay_config)
    if window.empty:
        return [], {"error": "candles_unavailable"}

    return asyncio.run(
        _run_replay_async(window=window, config=replay_config, legacy_config=cfg)
    )


def run_legacy_research_replay(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    tail_only: int | None = 400,
    days: int | None = None,
    stride: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Phase24A collect_production_decisions — legacy research path for comparison."""
    from tradingbot.ml.research.phase24a.live_shadow_validator import collect_production_decisions

    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"
    if tail_only is not None:
        return collect_production_decisions(
            base_dir=base_dir,
            symbol=symbol,
            timeframe=timeframe,
            tail_only=tail_only,
            stride=stride,
            use_mt5=False,
        )
    return collect_production_decisions(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=int(days or 7),
        stride=stride,
        use_mt5=False,
    )
