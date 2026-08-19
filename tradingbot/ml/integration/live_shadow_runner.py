"""Phase 10.2 — live MT5 shadow runner with full kernel pipeline."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.domain.models import MarketKey
from tradingbot.ml.data.paths import next_ml_live_shadow_run_id
from tradingbot.ml.integration.config import is_ml_shadow_mode
from tradingbot.ml.integration.error_audit.recovery_manager import ShadowRecoveryManager
from tradingbot.ml.integration.kernel_builder import build_kernel_shadow
from tradingbot.ml.integration.live_market_adapter import LiveMarketAdapter, LiveMarketKernelAdapter
from tradingbot.ml.integration.live_metrics import LiveMetricsTracker
from tradingbot.ml.integration.live_preflight import run_live_preflight
from tradingbot.ml.integration.live_run_logger import load_live_shadow_report, save_live_shadow_run
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME
from tradingbot.ml.integration.trade_integrity_logger import save_trade_integrity_artifacts
from tradingbot.ml.integration.virtual_trade_builder import VirtualTradeBuilder
from tradingbot.ml.paper_trading.paper_broker import BrokerConfig, PaperBroker

logger = logging.getLogger(__name__)
WARMUP_BARS = 80
MAX_HOLD_BARS = 72


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


@dataclass
class LiveShadowConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    model: str = "phase9_9_best"
    risk_pct: float = 0.005
    shadow_days: int = 7
    shadow_hours: int | None = None
    mode: str = "historical"  # historical | poll
    seed: int = 42
    poll_interval_sec: float = 30.0
    tp_r: float = 2.0
    sl_r: float = 1.0
    initial_equity: float = 10_000.0
    skip_preflight: bool = False
    candles_df: Any = None
    monitor: Any = None
    resume_from_bar: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "model": self.model,
            "risk_pct": self.risk_pct,
            "shadow_days": self.shadow_days,
            "shadow_hours": self.shadow_hours,
            "mode": self.mode,
            "seed": self.seed,
            "tp_r": self.tp_r,
            "sl_r": self.sl_r,
            "initial_equity": self.initial_equity,
        }


@dataclass
class _OpenVirtual:
    timestamp: str
    direction: int
    entry: float
    sl: float
    tp: float
    risk_amount: float
    lot: float
    atr: float = 0.0
    rr_ratio: float = 2.0
    bars_held: int = 0


@dataclass
class LiveShadowResult:
    run_id: str
    symbol: str
    timeframe: str
    status: str
    preflight_pass: bool
    duration_hours: float
    metrics: dict[str, Any]
    report_path: str
    paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "10.3",
            "run_id": self.run_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "preflight_pass": self.preflight_pass,
            "duration_hours": round(self.duration_hours, 4),
            "metrics": self.metrics,
            "report_path": self.report_path,
            "paths": self.paths,
            "order_send": False,
            "kernel_integrated": True,
        }


class LiveShadowRunner:
    """Execute TradingKernel on live MT5 data in shadow mode only."""

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    def run(self, config: LiveShadowConfig | None = None, *, run_id: str | None = None) -> LiveShadowResult:
        os.environ["ENABLE_ML_SHADOW"] = "true"
        os.environ["ML_SHADOW_MODE"] = "true"

        cfg = config or LiveShadowConfig()
        started = datetime.now(timezone.utc)
        symbol = cfg.symbol.upper()
        timeframe = cfg.timeframe.upper()
        market = MarketKey(symbol=symbol, timeframe=timeframe)

        legacy_config = load_legacy_config()
        legacy_config["RISK_PER_TRADE"] = cfg.risk_pct

        preflight = (
            {"preflight_pass": True, "skipped": True}
            if cfg.skip_preflight
            else run_live_preflight(symbol, timeframe, config=legacy_config, base_dir=self.base_dir)
        )
        if not preflight.get("preflight_pass") and not cfg.skip_preflight:
            raise RuntimeError(f"Live preflight failed: {preflight}")

        if cfg.candles_df is None:
            from tradingbot.adapters.mt5_utils import ensure_mt5_connected

            if not ensure_mt5_connected(legacy_config, symbols=[symbol], strict_account=False):
                raise RuntimeError("MT5 connection failed before live shadow run")

        live = LiveMarketAdapter(symbol, timeframe, legacy_config, candles=cfg.candles_df)
        if cfg.candles_df is None:
            if cfg.mode == "poll":
                live.load_history(days=max(1, (cfg.shadow_hours or 24) // 24 + 1))
            else:
                live.load_history(days=cfg.shadow_days)
        else:
            live.load_history()

        if cfg.monitor is not None and hasattr(cfg.monitor, "attach_candles"):
            cfg.monitor.attach_candles(live.candles)

        kernel_data = LiveMarketKernelAdapter(live)
        kernel, strategies, guard = build_kernel_shadow(
            kernel_data,  # type: ignore[arg-type]
            symbol=symbol,
            timeframe=timeframe,
            legacy_config=legacy_config,
            base_dir=str(self.base_dir) if self.base_dir else None,
            seed=cfg.seed,
        )
        broker = PaperBroker(BrokerConfig(tp_r=cfg.tp_r, sl_r=cfg.sl_r))
        trade_builder = VirtualTradeBuilder(risk_percent=cfg.risk_pct, tp_r=cfg.tp_r, sl_r=cfg.sl_r)
        recovery = ShadowRecoveryManager()
        tracker = LiveMetricsTracker(initial_equity=cfg.initial_equity, equity=cfg.initial_equity)

        events: list[dict[str, Any]] = []
        signals: list[dict[str, Any]] = []
        contexts: list[dict[str, Any]] = []
        risk_results: list[dict[str, Any]] = []
        virtual_orders: list[dict[str, Any]] = []
        virtual_trades: list[dict[str, Any]] = []
        invalid_trades: list[dict[str, Any]] = []
        trade_quality: list[dict[str, Any]] = []
        open_pos: _OpenVirtual | None = None

        end_time = started + timedelta(hours=cfg.shadow_hours or 0) if cfg.mode == "poll" and cfg.shadow_hours else None

        def process_bar(bar_index: int, candle_ts: str, spread: float | None) -> None:
            nonlocal open_pos

            if open_pos is not None:
                open_pos.bars_held += 1
                bar = live.candles.iloc[bar_index]
                hit = broker.resolve_bar(
                    bar,
                    direction=open_pos.direction,
                    stop_loss=open_pos.sl,
                    take_profit=open_pos.tp,
                )
                if hit or open_pos.bars_held >= MAX_HOLD_BARS:
                    result, exit_px = hit if hit else ("TIMEOUT", float(bar["close"]))
                    r_mult = cfg.tp_r if result == "TP" else (-cfg.sl_r if result == "SL" else 0.0)
                    pnl = r_mult * open_pos.risk_amount
                    trade = {
                        "timestamp": open_pos.timestamp,
                        "symbol": symbol,
                        "direction": open_pos.direction,
                        "entry": open_pos.entry,
                        "exit": round(exit_px, 4),
                        "sl": open_pos.sl,
                        "tp": open_pos.tp,
                        "atr": open_pos.atr,
                        "rr_ratio": open_pos.rr_ratio,
                        "result": result,
                        "R_multiple": round(r_mult, 4),
                        "pnl": round(pnl, 4),
                        "duration": open_pos.bars_held,
                    }
                    virtual_trades.append(trade)
                    tracker.record_trade(trade)
                    if cfg.monitor is not None and hasattr(cfg.monitor, "on_trade_close"):
                        cfg.monitor.on_trade_close(trade)
                        if tracker.equity_curve:
                            cfg.monitor.on_equity(tracker.equity_curve[-1])
                    open_pos = None
                return

            kernel_data.set_bar_index(bar_index)

            def _run_cycle():
                return asyncio.run(kernel.run_market_cycle(market))

            ctx = recovery.run_cycle(_run_cycle, timestamp=candle_ts, bar_index=bar_index)
            if ctx is None:
                contexts.append(
                    {
                        "timestamp": candle_ts,
                        "ml_in_kernel": False,
                        "has_signal": False,
                        "has_risk": False,
                        "errors": ["cycle_exception"],
                        "pipeline_errors": ["cycle_exception"],
                        "risk_blocks": [],
                    }
                )
                if cfg.monitor is not None and hasattr(cfg.monitor, "on_cycle"):
                    cfg.monitor.on_cycle(
                        event={"timestamp": candle_ts, "ml_signal": "HOLD"},
                        context=contexts[-1],
                        ml_meta={},
                        bar_index=bar_index,
                        pipeline_errors=["cycle_exception"],
                    )
                return

            meta = strategies.last_ml_meta
            ml_dir = meta.get("ml_direction", "HOLD")
            ml_prob = meta.get("ml_probability")
            ml_in_kernel = bool(ctx.signal and ctx.signal.strategy_name == STRATEGY_NAME)
            plan = None
            invalid = None

            event = _json_safe(
                {
                    "timestamp": candle_ts,
                    "symbol": symbol,
                    "ml_probability": ml_prob,
                    "ml_signal": ml_dir,
                    "kernel_signal": ctx.signal.direction.name if ctx.signal else "NONE",
                    "risk_allowed": ctx.risk.allowed if ctx.risk else None,
                    "risk_reason": ctx.risk.reason if ctx.risk else None,
                    "spread": spread,
                    "virtual_entry": (ctx.signal.metadata or {}).get("entry") if ctx.signal else None,
                    "virtual_sl": ctx.signal.stop_loss if ctx.signal else None,
                    "virtual_tp": ctx.signal.take_profit if ctx.signal else None,
                    "result": None,
                    "execution_status": ctx.execution.message if ctx.execution else None,
                }
            )
            events.append(event)
            pipeline_errs, risk_blocks = recovery.classify_context_errors(list(ctx.errors))
            contexts.append(
                {
                    "timestamp": candle_ts,
                    "ml_in_kernel": ml_in_kernel,
                    "has_signal": ctx.signal is not None,
                    "has_risk": ctx.risk is not None,
                    "errors": list(ctx.errors),
                    "pipeline_errors": pipeline_errs,
                    "risk_blocks": risk_blocks,
                }
            )

            tracker.record_cycle(
                ml_direction=str(ml_dir),
                confidence=float((ctx.signal.confidence if ctx.signal else 0.0) or 0.0),
                spread=spread,
                kernel_has_signal=ctx.signal is not None,
                ml_in_kernel=ml_in_kernel,
                risk_allowed=ctx.risk.allowed if ctx.risk else None,
                risk_reason=ctx.risk.reason if ctx.risk else None,
                execution_blocked=bool(ctx.execution and not ctx.execution.success),
            )

            if ctx.signal is not None:
                signals.append(
                    _json_safe(
                        {
                            "timestamp": candle_ts,
                            "direction": ctx.signal.direction.name,
                            "strategy_name": ctx.signal.strategy_name,
                            "confidence": float(ctx.signal.confidence),
                            "metadata": dict(ctx.signal.metadata or {}),
                        }
                    )
                )
            if ctx.risk is not None:
                risk_results.append(
                    _json_safe(
                        {
                            "timestamp": candle_ts,
                            "allowed": ctx.risk.allowed,
                            "reason": ctx.risk.reason,
                            "adjusted_lot": ctx.risk.adjusted_lot,
                        }
                    )
                )

            if ctx.risk and ctx.risk.allowed and ctx.signal is not None:
                plan, invalid = trade_builder.build(
                    candles=live.candles,
                    bar_index=bar_index,
                    direction=ctx.signal.direction.name,
                    symbol=symbol,
                    timestamp=candle_ts,
                    equity=tracker.equity,
                    risk_lot=ctx.risk.adjusted_lot,
                )
                if invalid is not None:
                    invalid_trades.append(_json_safe(invalid))
                    events[-1]["integrity_blocked"] = invalid.get("blocked_reason")
                    events[-1]["virtual_entry"] = invalid.get("entry")
                    events[-1]["virtual_sl"] = invalid.get("sl")
                    events[-1]["virtual_tp"] = invalid.get("tp")
                    if cfg.monitor is not None and hasattr(cfg.monitor, "on_cycle"):
                        cfg.monitor.on_cycle(
                            event=events[-1],
                            context=contexts[-1],
                            ml_meta=meta,
                            bar_index=bar_index,
                            pipeline_errors=pipeline_errs,
                            risk_blocks=risk_blocks,
                            invalid_trade=invalid,
                        )
                    return

                assert plan is not None
                order = plan.to_order_dict(ml_probability=ml_prob)
                trade_quality.append(_json_safe(plan.to_quality_dict()))
                virtual_orders.append(_json_safe(order))
                events[-1]["virtual_entry"] = plan.entry
                events[-1]["virtual_sl"] = plan.stop_loss
                events[-1]["virtual_tp"] = plan.take_profit
                events[-1]["validation_status"] = plan.validation_status

                if is_ml_shadow_mode():
                    dir_int = 1 if plan.direction == "BUY" else -1
                    open_pos = _OpenVirtual(
                        timestamp=candle_ts,
                        direction=dir_int,
                        entry=plan.entry,
                        sl=plan.stop_loss,
                        tp=plan.take_profit,
                        risk_amount=plan.risk_amount,
                        lot=plan.lot,
                        atr=plan.atr,
                        rr_ratio=plan.rr_ratio,
                    )

            if cfg.monitor is not None and hasattr(cfg.monitor, "on_cycle"):
                cfg.monitor.on_cycle(
                    event=events[-1],
                    context=contexts[-1],
                    ml_meta=meta,
                    bar_index=bar_index,
                    pipeline_errors=pipeline_errs,
                    risk_blocks=risk_blocks,
                    trade_quality=plan.to_quality_dict() if plan is not None else None,
                    invalid_trade=None,
                )
                if cfg.monitor.kernel_cycles % 100 == 0 and hasattr(cfg.monitor, "save_checkpoint"):
                    cfg.monitor.save_checkpoint()

        start_bar = WARMUP_BARS
        if cfg.resume_from_bar is not None and cfg.resume_from_bar >= WARMUP_BARS:
            start_bar = cfg.resume_from_bar + 1

        if cfg.mode == "poll" and cfg.shadow_hours:
            while datetime.now(timezone.utc) < end_time:  # type: ignore[operator]
                candle = live.poll_latest_closed()
                if candle is not None:
                    process_bar(live.bar_index, candle.timestamp, candle.spread)
                time.sleep(cfg.poll_interval_sec)
        else:
            for i, candle in live.iter_closed_bars(start_index=start_bar):
                process_bar(i, candle.timestamp, candle.spread)

        virtual_orders.extend(_json_safe(o) for o in guard.virtual_trades)

        metrics = tracker.compute().to_dict()
        duration_h = (datetime.now(timezone.utc) - started).total_seconds() / 3600.0
        rid = run_id or next_ml_live_shadow_run_id(self.base_dir)

        integrity_paths = save_trade_integrity_artifacts(
            rid,
            valid_trades=trade_quality,
            invalid_trades=invalid_trades,
            base_dir=self.base_dir,
            extra={"symbol": symbol, "timeframe": timeframe},
        )

        paths = save_live_shadow_run(
            rid,
            events=events,
            signals=signals,
            kernel_context=contexts,
            risk_results=risk_results,
            virtual_orders=virtual_orders,
            virtual_trades=virtual_trades,
            equity_curve=tracker.equity_curve,
            metrics=metrics,
            config={**cfg.to_dict(), "preflight": preflight},
            extra={
                "preflight_pass": bool(preflight.get("preflight_pass")),
                "duration_hours": duration_h,
                "mt5_broker_symbol": live.broker_symbol,
                "recovery": recovery.state.to_dict(),
                "trade_integrity": {
                    "valid_trades": len(trade_quality),
                    "invalid_trades": len(invalid_trades),
                    "paths": {k: str(v) for k, v in integrity_paths.items()},
                },
            },
            base_dir=self.base_dir,
        )

        status = "PASS" if metrics.get("kernel_cycles", 0) >= 1 else "FAIL"
        return LiveShadowResult(
            run_id=rid,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            preflight_pass=bool(preflight.get("preflight_pass")),
            duration_hours=duration_h,
            metrics=metrics,
            report_path=str(paths["report"]),
            paths={k: str(v) for k, v in {**paths, **integrity_paths}.items()},
        )

    def report_only(self, run_id: str) -> dict[str, Any]:
        return load_live_shadow_report(run_id, self.base_dir)
