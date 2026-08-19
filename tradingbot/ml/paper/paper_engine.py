"""Phase 11 — kernel-integrated paper trading engine."""

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
from tradingbot.ml.data.paths import next_paper_trading_run_id, paper_trading_final_report_path
from tradingbot.ml.integration.config import is_ml_shadow_mode
from tradingbot.ml.integration.error_audit.recovery_manager import ShadowRecoveryManager
from tradingbot.ml.integration.error_audit.kernel_error_analyzer import split_kernel_errors
from tradingbot.ml.integration.kernel_builder import build_kernel_shadow
from tradingbot.ml.integration.live_market_adapter import LiveMarketAdapter, LiveMarketKernelAdapter
from tradingbot.ml.integration.live_preflight import run_live_preflight, scan_live_shadow_ast
from tradingbot.ml.integration.ml_strategy import STRATEGY_NAME
from tradingbot.ml.paper.config import PaperTradingConfig, validate_frozen_model
from tradingbot.ml.paper.daily_report import build_daily_metrics, save_paper_run
from tradingbot.ml.paper.paper_execution import PaperExecutionEngine
from tradingbot.ml.paper.performance import compute_performance
from tradingbot.ml.paper.portfolio_manager import PortfolioManager
from tradingbot.ml.paper.session_analyzer import analyze_sessions, compare_to_phase105
from tradingbot.ml.paper.trade_lifecycle import TradeLifecycle
from tradingbot.ml.paper.virtual_account import VirtualAccount

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


@dataclass
class PaperRunResult:
    run_id: str
    status: str
    decision: str
    num_trades: int
    metrics: dict[str, Any]
    report_path: str
    paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "11",
            "run_id": self.run_id,
            "status": self.status,
            "decision": self.decision,
            "num_trades": self.num_trades,
            "metrics": self.metrics,
            "report_path": self.report_path,
            "paths": self.paths,
            "order_send": False,
        }


class KernelPaperEngine:
    """MT5 read-only → TradingKernel → ML → RiskGate → virtual paper execution."""

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    def run(self, config: PaperTradingConfig | None = None, *, run_id: str | None = None) -> PaperRunResult:
        os.environ["ENABLE_ML_SHADOW"] = "true"
        os.environ["ML_SHADOW_MODE"] = "true"

        violations = scan_live_shadow_ast()
        if violations:
            raise RuntimeError(f"AST safety violations: {violations}")

        cfg = config or PaperTradingConfig()
        if not cfg.skip_model_validation:
            model_report = validate_frozen_model(base_dir=self.base_dir)
        else:
            model_report = {"status": "SKIPPED"}

        started = datetime.now(timezone.utc)
        symbol = cfg.symbol.upper()
        timeframe = cfg.timeframe.upper()
        market = MarketKey(symbol=symbol, timeframe=timeframe)

        legacy_config = load_legacy_config()
        legacy_config["RISK_PER_TRADE"] = cfg.risk_pct

        if not cfg.skip_preflight:
            preflight = run_live_preflight(symbol, timeframe, config=legacy_config, base_dir=self.base_dir)
            if not preflight.get("preflight_pass"):
                raise RuntimeError(f"Preflight failed: {preflight}")
        else:
            preflight = {"preflight_pass": True, "skipped": True}

        if cfg.candles_df is None:
            from tradingbot.adapters.mt5_utils import ensure_mt5_connected

            if not ensure_mt5_connected(legacy_config, symbols=[symbol], strict_account=False):
                raise RuntimeError("MT5 connection failed")

        live = LiveMarketAdapter(symbol, timeframe, legacy_config, candles=cfg.candles_df)
        if cfg.candles_df is None:
            live.load_history(days=cfg.paper_days)
        else:
            live.load_history()

        kernel_data = LiveMarketKernelAdapter(live)
        kernel, strategies, guard = build_kernel_shadow(
            kernel_data,  # type: ignore[arg-type]
            symbol=symbol,
            timeframe=timeframe,
            legacy_config=legacy_config,
            base_dir=str(self.base_dir) if self.base_dir else None,
            seed=cfg.seed,
        )

        account = VirtualAccount(initial_balance=cfg.initial_balance, balance=cfg.initial_balance, equity=cfg.initial_balance)
        lifecycle = TradeLifecycle(tp_r=cfg.tp_r, sl_r=cfg.sl_r, max_hold_bars=cfg.max_hold_bars)
        portfolio = PortfolioManager(account, lifecycle)
        paper_exec = PaperExecutionEngine(risk_percent=cfg.risk_pct, tp_r=cfg.tp_r, sl_r=cfg.sl_r)
        recovery = ShadowRecoveryManager()

        cycles_log: list[dict[str, Any]] = []
        risk_reasons: dict[str, int] = {}
        ml_buy = ml_sell = ml_hold = 0
        risk_allowed = risk_blocked = 0
        kernel_cycles = 0
        pipeline_errors = 0

        end_time = (
            started + timedelta(hours=cfg.paper_hours or 0)
            if cfg.mode == "live" and cfg.paper_hours
            else None
        )

        def process_bar(bar_index: int, candle_ts: str, spread: float | None) -> None:
            nonlocal ml_buy, ml_sell, ml_hold, risk_allowed, risk_blocked, kernel_cycles, pipeline_errors

            closed = portfolio.monitor_bar(live.candles.iloc[bar_index])
            if closed is not None:
                return

            kernel_data.set_bar_index(bar_index)

            def _run_cycle():
                return asyncio.run(kernel.run_market_cycle(market))

            ctx = recovery.run_cycle(_run_cycle, timestamp=candle_ts, bar_index=bar_index)
            kernel_cycles += 1
            if ctx is None:
                pipeline_errors += 1
                cycles_log.append(
                    _json_safe(
                        {
                            "timestamp": candle_ts,
                            "paper_action": "SKIP",
                            "pipeline_error": True,
                        }
                    )
                )
                return

            meta = strategies.last_ml_meta
            ml_dir = str(meta.get("ml_direction", "HOLD")).upper()
            ml_prob = meta.get("ml_probability")
            if ml_dir == "BUY":
                ml_buy += 1
            elif ml_dir == "SELL":
                ml_sell += 1
            else:
                ml_hold += 1

            pipe_errs, risk_blocks = split_kernel_errors(list(ctx.errors))
            if pipe_errs:
                pipeline_errors += len(pipe_errs)

            cycle_row: dict[str, Any] = {
                "timestamp": candle_ts,
                "ml_signal": ml_dir,
                "ml_probability": ml_prob,
                "kernel_signal": ctx.signal.direction.name if ctx.signal else "NONE",
                "ml_in_kernel": bool(ctx.signal and ctx.signal.strategy_name == STRATEGY_NAME),
                "risk_allowed": bool(ctx.risk and ctx.risk.allowed),
                "risk_reason": ctx.risk.reason if ctx.risk else None,
                "spread": spread,
                "paper_action": "NONE",
                "pipeline_errors": pipe_errs,
                "risk_blocks": risk_blocks,
            }

            if ctx.risk and ctx.risk.allowed:
                risk_allowed += 1
            elif ctx.risk and not ctx.risk.allowed:
                risk_blocked += 1
                key = str(ctx.risk.reason or "unknown").split("(")[0].strip()
                risk_reasons[key] = risk_reasons.get(key, 0) + 1

            if (
                ctx.risk
                and ctx.risk.allowed
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
                    risk_lot=ctx.risk.adjusted_lot,
                    ml_probability=float(ml_prob) if ml_prob is not None else None,
                )
                if invalid is not None:
                    cycle_row["paper_action"] = "REJECTED_INTEGRITY"
                elif order is not None:
                    portfolio.open_position(order)
                    cycle_row["paper_action"] = "OPEN"

            cycles_log.append(_json_safe(cycle_row))

        if cfg.mode == "live" and cfg.paper_hours:
            while datetime.now(timezone.utc) < end_time:  # type: ignore[operator]
                candle = live.poll_latest_closed()
                if candle is not None:
                    process_bar(live.bar_index, candle.timestamp, candle.spread)
                time.sleep(cfg.poll_interval_sec)
        else:
            for i, candle in live.iter_closed_bars(start_index=WARMUP_BARS):
                process_bar(i, candle.timestamp, candle.spread)

        trades = [t.to_dict() for t in portfolio.closed_trades]
        performance = compute_performance(
            portfolio.closed_trades,
            ml_buy=ml_buy,
            ml_sell=ml_sell,
            ml_hold=ml_hold,
            risk_allowed=risk_allowed,
            risk_blocked=risk_blocked,
            risk_reasons=risk_reasons,
            virtual_executions=paper_exec.virtual_executions,
            rejected_trades=paper_exec.rejected_trades,
            integrity_failures=len(paper_exec.integrity_failures),
            initial_balance=cfg.initial_balance,
            equity_curve=portfolio.equity_curve,
        )

        session = analyze_sessions(portfolio.closed_trades)
        daily = build_daily_metrics(cycles_log)
        duration_days = cfg.paper_days if cfg.mode == "replay" else (cfg.paper_hours or 0) / 24.0

        integrity_report = {
            "integrity_failures": paper_exec.integrity_failures,
            "failure_count": len(paper_exec.integrity_failures),
            "all_rr_valid": all(abs(t.order.rr_ratio - 2.0) < 0.05 for t in portfolio.closed_trades),
        }

        phase105_ref = _load_phase105_reference(self.base_dir)
        analysis = {
            "ml_signal_stable": ml_hold / max(1, ml_buy + ml_sell + ml_hold) < 0.99,
            "sell_bias": session.get("sell_bias"),
            "best_session": session.get("best_session"),
            "drawdown_acceptable": performance["trading"]["max_drawdown"] < 0.10,
            "phase105_comparison": compare_to_phase105(performance, phase105_ref),
        }

        passed = (
            integrity_report["failure_count"] == 0
            and pipeline_errors == 0
            and performance["execution"]["order_send"] is False
        )

        decision = "PASS"
        if not passed:
            decision = "NEEDS REVIEW"
        elif cfg.paper_days < 30 and cfg.candles_df is None and not cfg.paper_hours:
            decision = "NEEDS REVIEW"  # production requires >=30d historical
        elif performance["trading"]["profit_factor"] < 1.0 or performance["trading"]["expectancy_r"] < 0:
            decision = "NEEDS REVIEW"

        rid = run_id or next_paper_trading_run_id(self.base_dir)
        final_report = {
            "phase": "11",
            "run_id": rid,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "duration_days": duration_days,
            "kernel_cycles": kernel_cycles,
            "pipeline_errors": pipeline_errors,
            "preflight": preflight,
            "model_validation": model_report,
            "performance": performance,
            "analysis": analysis,
            "decision": decision,
            "order_send": False,
            "recovery": recovery.state.to_dict(),
        }

        paths = save_paper_run(
            rid,
            trades=trades,
            equity_curve=portfolio.equity_curve,
            daily_metrics=daily,
            session_metrics=session,
            risk_report=performance["risk"],
            integrity_report=integrity_report,
            final_report=final_report,
            config={**cfg.to_dict(), "preflight": preflight, "model_validation": model_report},
            cycles=cycles_log,
            base_dir=self.base_dir,
        )

        status = "PASS" if decision == "PASS" else "NEEDS_REVIEW"
        return PaperRunResult(
            run_id=rid,
            status=status,
            decision=decision,
            num_trades=len(trades),
            metrics=performance,
            report_path=str(paths["final_report"]),
            paths={k: str(v) for k, v in paths.items()},
        )

    def report_only(self, run_id: str) -> dict[str, Any]:
        path = paper_trading_final_report_path(run_id, self.base_dir)
        if not path.is_file():
            raise FileNotFoundError(f"Paper run not found: {run_id}")
        import json

        return json.loads(path.read_text(encoding="utf-8"))


def _load_phase105_reference(base_dir: str | Path | None) -> dict[str, Any] | None:
    import json

    from tradingbot.ml.data.paths import ml_shadow_monitor_final_report_path

    path = ml_shadow_monitor_final_report_path("stability_fixed_v1", base_dir)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("trading") or data.get("performance", {}).get("trading")
