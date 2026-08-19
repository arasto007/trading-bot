"""Phase 12 — controlled live pilot controller."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.domain.models import MarketKey
from tradingbot.ml.dataset.labels import compute_atr_at
from tradingbot.ml.integration.config import is_ml_shadow_mode
from tradingbot.ml.integration.error_audit.kernel_error_analyzer import split_kernel_errors
from tradingbot.ml.integration.error_audit.recovery_manager import ShadowRecoveryManager
from tradingbot.ml.integration.kernel_builder import build_kernel_shadow
from tradingbot.ml.integration.live_market_adapter import LiveMarketAdapter, LiveMarketKernelAdapter
from tradingbot.ml.integration.live_preflight import run_live_preflight, scan_live_shadow_ast
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME
from tradingbot.ml.live_pilot.config import (
    PilotConfig,
    ab_signals,
    apply_mode_env,
    is_pilot_live_enabled,
    resolve_mode,
    session_for_hour,
)
from tradingbot.ml.live_pilot.execution_guard import PilotExecutionGuard, create_mt5_executor
from tradingbot.ml.live_pilot.kill_switch import PilotKillSwitch
from tradingbot.ml.live_pilot.live_monitor import LiveMonitor
from tradingbot.ml.live_pilot.position_limiter import PositionLimiter
from tradingbot.ml.live_pilot.safety_manager import SafetyManager
from tradingbot.ml.live_pilot.trade_journal import TradeJournal
from tradingbot.ml.paper.config import validate_frozen_model
from tradingbot.ml.paper.paper_execution import PaperExecutionEngine
from tradingbot.ml.paper.portfolio_manager import PortfolioManager
from tradingbot.ml.paper.trade_lifecycle import TradeLifecycle
from tradingbot.ml.paper.virtual_account import VirtualAccount
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime

logger = logging.getLogger(__name__)
WARMUP_BARS = 80


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


def classify_pilot_regime(df: pd.DataFrame, index: int) -> str:
    """Research overlay — does not modify regime detector."""
    atr = float(compute_atr_at(df, index))
    atrs = [float(compute_atr_at(df, i)) for i in range(max(0, index - 100), index + 1)]
    p33 = float(np.percentile(atrs, 33)) if atrs else atr
    if atr <= p33:
        return "LOW_VOLATILITY"
    row = pd.Series({"atr_percentile": 50.0, "ema50_slope": 0.0, "structure_distance": 0.0})
    try:
        return str(assign_market_regime(pd.DataFrame([row])).iloc[0])
    except Exception:
        return "RANGE"


@dataclass
class PilotRunResult:
    run_id: str
    mode: str
    status: str
    recommendation: str
    report_path: str
    paths: dict[str, str] = field(default_factory=dict)
    order_send: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "12",
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "recommendation": self.recommendation,
            "report_path": self.report_path,
            "paths": self.paths,
            "order_send": self.order_send,
        }


class LiveController:
    """MT5 → TradingKernel → ML → RiskGate → Phase12 Safety → Execution."""

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir
        self._current_regime = "RANGE"
        self._current_spread: float | None = None

    def run(self, config: PilotConfig | None = None) -> PilotRunResult:
        cfg = config or PilotConfig()
        mode = resolve_mode(cfg.mode)
        cfg.mode = mode
        apply_mode_env(mode)

        violations = scan_live_shadow_ast()
        if violations:
            raise RuntimeError(f"Integration AST violations: {violations}")

        model_report: dict[str, Any]
        if not cfg.skip_model_validation:
            model_report = validate_frozen_model(base_dir=self.base_dir)
        else:
            model_report = {"status": "SKIPPED"}

        checksum_valid = model_report.get("status") == "PASS"
        legacy_config = load_legacy_config()
        legacy_config["RISK_PER_TRADE"] = cfg.risk_pct
        legacy_config["MAX_OPEN_POSITIONS_TOTAL"] = cfg.max_open_positions
        legacy_config["MAX_OPEN_POSITIONS_PER_SYMBOL"] = cfg.max_open_positions
        legacy_config["MAX_TRADES_PER_DAY"] = cfg.max_trades_per_day

        if not cfg.skip_preflight:
            preflight = run_live_preflight(
                cfg.symbol, cfg.timeframe, config=legacy_config, base_dir=self.base_dir
            )
            if not preflight.get("preflight_pass"):
                raise RuntimeError(f"Preflight failed: {preflight}")
        else:
            preflight = {"preflight_pass": True, "skipped": True}

        symbol = cfg.symbol.upper()
        timeframe = cfg.timeframe.upper()
        market = MarketKey(symbol=symbol, timeframe=timeframe)
        run_id = cfg.run_id if cfg.run_id.startswith("run_") else f"run_{cfg.run_id}"

        journal = TradeJournal(run_id, base_dir=self.base_dir)
        journal.write_config(cfg.to_dict())

        kill_switch = PilotKillSwitch()
        if not checksum_valid:
            kill_switch.check_checksum(False)

        position_limiter = PositionLimiter(
            max_open_positions=cfg.max_open_positions,
            max_trades_per_day=cfg.max_trades_per_day,
            max_consecutive_losses=cfg.max_consecutive_losses,
        )
        safety = SafetyManager(
            cfg,
            kill_switch=kill_switch,
            position_limiter=position_limiter,
            model_checksum_valid=checksum_valid,
        )
        monitor = LiveMonitor()

        from tradingbot.adapters.mt5_utils import ensure_mt5_connected

        if not ensure_mt5_connected(legacy_config, symbols=[symbol], strict_account=False):
            raise RuntimeError("MT5 connection failed")

        live = LiveMarketAdapter(symbol, timeframe, legacy_config)
        live.load_history(days=cfg.pilot_days)
        kernel_data = LiveMarketKernelAdapter(live)
        kernel, strategies, guard = build_kernel_shadow(
            kernel_data,
            symbol=symbol,
            timeframe=timeframe,
            legacy_config=legacy_config,
            base_dir=str(self.base_dir) if self.base_dir else None,
            seed=cfg.seed,
        )

        pilot_guard: PilotExecutionGuard | None = None
        if mode == "PILOT":
            inner = create_mt5_executor(legacy_config)
            pilot_guard = PilotExecutionGuard(
                inner,
                safety=safety,
                journal=journal,
                spread_provider=lambda: self._current_spread,
                regime_provider=lambda: self._current_regime,
            )
            guard._inner = pilot_guard

        paper_exec: PaperExecutionEngine | None = None
        portfolio: PortfolioManager | None = None
        account: VirtualAccount | None = None
        if mode == "PAPER":
            account = VirtualAccount(
                initial_balance=cfg.initial_balance,
                balance=cfg.initial_balance,
                equity=cfg.initial_balance,
            )
            lifecycle = TradeLifecycle(tp_r=cfg.tp_r, sl_r=cfg.sl_r)
            portfolio = PortfolioManager(account, lifecycle)
            paper_exec = PaperExecutionEngine(risk_percent=cfg.risk_pct, tp_r=cfg.tp_r, sl_r=cfg.sl_r)

        recovery = ShadowRecoveryManager()
        trades_closed: list[dict[str, Any]] = []
        started = datetime.now(timezone.utc)
        end_time = started + timedelta(days=cfg.pilot_days)

        def process_bar(bar_index: int, candle_ts: str, spread: float | None = None) -> None:
            if portfolio is not None:
                closed = portfolio.monitor_bar(live.candles.iloc[bar_index])
                if closed is not None:
                    row = closed.to_dict()
                    trades_closed.append(row)
                    journal.log_trade(_json_safe(row))
                    position_limiter.record_exit(won=float(row.get("pnl", 0)) > 0)

            kernel_data.set_bar_index(bar_index)
            self._current_regime = classify_pilot_regime(live.candles, bar_index)
            self._current_spread = spread

            def _run_cycle():
                return asyncio.run(kernel.run_market_cycle(market))

            ctx = recovery.run_cycle(_run_cycle, timestamp=candle_ts, bar_index=bar_index)
            if ctx is None:
                journal.log_error({"timestamp": candle_ts, "error": "pipeline_failure"})
                return

            meta = strategies.last_ml_meta
            ml_prob = meta.get("ml_probability")
            ab = ab_signals(ml_prob if ml_prob is not None else None)
            hour = pd.Timestamp(candle_ts).hour
            regime_ok = self._current_regime in cfg.allowed_regimes

            journal.log_signal(
                _json_safe(
                    {
                        "timestamp": candle_ts,
                        "symbol": symbol,
                        "strategy_a_signal": ab["strategy_a"],
                        "strategy_b_signal": ab["strategy_b"],
                        "model_probability": ab.get("probability"),
                        "threshold_version_a": "A_0.55_0.45",
                        "threshold_version_b": "B_0.50_0.40",
                        "regime": self._current_regime,
                        "regime_accepted": regime_ok,
                        "sessions": session_for_hour(hour),
                    }
                )
            )

            risk_allowed = bool(ctx.risk and ctx.risk.allowed)
            risk_reason = ctx.risk.reason if ctx.risk else None
            journal.log_risk(
                _json_safe(
                    {
                        "timestamp": candle_ts,
                        "allowed": risk_allowed,
                        "reason": risk_reason,
                        "adjusted_lot": getattr(ctx.risk, "adjusted_lot", None) if ctx.risk else None,
                    }
                )
            )

            monitor.record_cycle(
                ml_direction=str(ab["strategy_a"]),
                risk_allowed=risk_allowed,
                risk_reason=risk_reason,
                hour_utc=hour,
                regime=self._current_regime,
                regime_accepted=regime_ok,
            )

            pipe_errs, _ = split_kernel_errors(list(ctx.errors))
            if pipe_errs:
                for err in pipe_errs:
                    journal.log_error({"timestamp": candle_ts, "pipeline_error": str(err)})

            if not risk_allowed or not ctx.signal:
                return
            if ctx.signal.strategy_name != STRATEGY_NAME:
                return
            if cfg.regime_filter_block and not regime_ok:
                return

            lot = float(getattr(ctx.risk, "adjusted_lot", 0.01) or 0.01)

            if (
                mode == "PAPER"
                and paper_exec is not None
                and portfolio is not None
                and account is not None
                and risk_allowed
                and ctx.signal is not None
                and portfolio.can_open()
                and is_ml_shadow_mode()
            ):
                order, invalid = paper_exec.create_order(
                    candles=live.candles,
                    bar_index=bar_index,
                    direction=ctx.signal.direction.name,
                    symbol=symbol,
                    timestamp=candle_ts,
                    equity=account.equity,
                    risk_lot=lot,
                    ml_probability=float(ml_prob) if ml_prob is not None else None,
                )
                if order is not None:
                    portfolio.open_position(order)
                    position_limiter.record_entry()
                    journal.log_trade(
                        _json_safe(
                            {
                                "timestamp": candle_ts,
                                "symbol": symbol,
                                "direction": ctx.signal.direction.name,
                                "volume": order.lot,
                                "entry": order.entry,
                                "sl": order.sl,
                                "tp": order.tp,
                                "model_probability": ml_prob,
                                "threshold_version": "A_0.55_0.45",
                                "regime": self._current_regime,
                                "session": session_for_hour(hour),
                                "risk_percent": cfg.risk_pct,
                                "mode": "PAPER",
                                "result": "OPEN",
                            }
                        )
                    )
                elif invalid is not None:
                    journal.log_error({"timestamp": candle_ts, "integrity": invalid})

        for i, candle in live.iter_closed_bars(start_index=WARMUP_BARS):
            process_bar(i, candle.timestamp, candle.spread)
            if datetime.now(timezone.utc) >= end_time:
                break

        if portfolio is not None:
            trades_closed.extend([t.to_dict() for t in portfolio.closed_trades])

        exec_stats = pilot_guard.stats if pilot_guard else {"attempts": 0, "success": 0, "rejected": 0}
        journal_paths = journal.flush()
        report = monitor.build_report(
            mode=mode,
            run_id=run_id,
            safety_summary=safety.summary(),
            execution_stats=exec_stats,
            trades=trades_closed,
            kill_switch=kill_switch.to_dict(),
            model_validation=model_report,
            preflight=preflight,
        )
        report_path = monitor.save_report(report, base_dir=str(self.base_dir) if self.base_dir else None)

        live_orders = mode == "PILOT" and is_pilot_live_enabled()
        status = "PASS" if report["recommendation"] in ("READY_FOR_SCALE",) else "NEEDS_REVIEW"
        if kill_switch.active:
            status = "KILL_SWITCH"

        return PilotRunResult(
            run_id=run_id,
            mode=mode,
            status=status,
            recommendation=report["recommendation"],
            report_path=report_path,
            paths=journal_paths,
            order_send=live_orders,
        )
