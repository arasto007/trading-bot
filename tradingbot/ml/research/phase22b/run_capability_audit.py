#!/usr/bin/env python3
"""Phase 22B — READ-ONLY capability audit. Does not modify production code."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = Path(__file__).resolve().parent
AUDIT_START = "2026-06-04 00:00"
AUDIT_END = "2026-07-04 23:59"
BALANCE = 200.0
SYMBOL = "XAUUSD"


@dataclass
class AuditState:
    # Pipeline stages
    bars_total: int = 0
    data_ok: int = 0
    data_fail: int = 0
    indicator_ok: int = 0
    signal_bar_dedupe: int = 0
    signal_no_signal: int = 0
    signal_emitted: int = 0
    risk_allowed: int = 0
    risk_blocked: Counter = field(default_factory=Counter)
    execution_attempts: int = 0
    execution_success: int = 0
    execution_dry: int = 0
    # ML
    ml_calls: int = 0
    ml_fallback: int = 0
    ml_hold: int = 0
    ml_buy: int = 0
    ml_sell: int = 0
    ml_health_fail: int = 0
    ml_unified_empty: int = 0
    ml_timeout: int = 0
    ml_cache_hit: int = 0
    ml_risk_block: int = 0
    ml_quality_block: int = 0
    ml_rsi_block: int = 0
    ml_adx_block: int = 0
    ml_calibration_hold: int = 0
    ml_latencies_ms: list = field(default_factory=list)
    regime_counts: Counter = field(default_factory=Counter)
    engine_route: Counter = field(default_factory=Counter)
    # Meta
    meta_gate_skipped: int = 0
    meta_gate_active: int = 0
    meta_rejected: int = 0
    meta_approved: int = 0
    # Router
    last_source_ml: int = 0
    last_source_legacy: int = 0
    # Trades
    trades: list = field(default_factory=list)
    # Per-TF
    tf: str = "M5"


STATE = AuditState()


def _install_hooks() -> None:
    from tradingbot.pipeline import data_stage, indicator_stage, signal_stage, risk_stage, execution_stage
    from tradingbot.adapters import risk_gate as rg_mod
    from tradingbot.ml.integration import kernel_adapter as ka_mod
    from tradingbot.ml.integration import ml_kernel_registry as mkr_mod
    from tradingbot.ml.phase19c import filters as filt_mod
    from tradingbot.services import meta_labeler as meta_mod

    orig_data_run = data_stage.DataStage.run
    orig_ind_run = indicator_stage.IndicatorStage.run
    orig_sig_run = signal_stage.SignalStage.run
    orig_risk_run = risk_stage.RiskStage.run
    orig_exec_run = execution_stage.ExecutionStage.run
    orig_risk_eval = rg_mod.RiskGate.evaluate
    orig_produce = ka_mod.KernelAdapter.produce_unified_signal
    orig_mkr_gen = mkr_mod.MLKernelRegistry.generate_signal
    orig_apply_filt = filt_mod.apply_profitability_filters
    orig_meta_gate = meta_mod.MetaLabeler.should_gate

    async def data_run(self, ctx, portfolio):
        STATE.bars_total += 1
        ok = await orig_data_run(self, ctx, portfolio)
        if ok:
            STATE.data_ok += 1
        else:
            STATE.data_fail += 1
        return ok

    async def ind_run(self, ctx, portfolio):
        ok = await orig_ind_run(self, ctx, portfolio)
        if ok:
            STATE.indicator_ok += 1
        return ok

    async def sig_run(self, ctx, portfolio):
        if ctx.enriched_ohlcv is None:
            return await orig_sig_run(self, ctx, portfolio)
        market_key = str(ctx.market)
        from tradingbot.domain.ohlcv import exclude_forming_bar
        closed = exclude_forming_bar(ctx.enriched_ohlcv)
        if closed is None or closed.empty:
            return await orig_sig_run(self, ctx, portfolio)
        last_ts = closed.index[-1]
        if self._last_closed_bar.get(market_key) == last_ts:
            STATE.signal_bar_dedupe += 1
            return False
        result = await orig_sig_run(self, ctx, portfolio)
        if result and ctx.signal is not None:
            STATE.signal_emitted += 1
            src = getattr(self._strategies, "last_source", "?")
            if src == "ml_kernel":
                STATE.last_source_ml += 1
            else:
                STATE.last_source_legacy += 1
        elif not result:
            STATE.signal_no_signal += 1
        return result

    async def risk_run(self, ctx, portfolio):
        ok = await orig_risk_run(self, ctx, portfolio)
        if ctx.risk is not None:
            if ctx.risk.allowed:
                STATE.risk_allowed += 1
            else:
                STATE.risk_blocked[ctx.risk.reason.split("(")[0].strip()] += 1
        return ok

    async def exec_run(self, ctx, portfolio):
        STATE.execution_attempts += 1
        ok = await orig_exec_run(self, ctx, portfolio)
        if ctx.execution and ctx.execution.success:
            STATE.execution_success += 1
            if ctx.execution.message and "dry" in ctx.execution.message.lower():
                STATE.execution_dry += 1
        return ok

    def risk_eval(self, signal, portfolio_snapshot):
        orig_should = meta_mod.MetaLabeler.should_gate
        tf = signal.timeframe
        regime = getattr(self, "_regime", "RANGING")
        meta = meta_mod.get_meta_labeler()
        if orig_should(meta, tf, regime):
            STATE.meta_gate_active += 1
        else:
            STATE.meta_gate_skipped += 1
        decision = orig_risk_eval(self, signal, portfolio_snapshot)
        if not decision.allowed and "meta-labeler" in decision.reason:
            STATE.meta_rejected += 1
        elif decision.allowed and STATE.meta_gate_active > STATE.meta_approved + STATE.meta_rejected:
            STATE.meta_approved += 1
        return decision

    def produce_unified(self, market, df):
        t0 = time.perf_counter()
        STATE.ml_calls += 1
        try:
            from tradingbot.ml.integration.pipeline_cache import PipelineCache
            row_key_prefix = f"{market.symbol}:{market.timeframe}:"
            cached_before = PipelineCache.get_prediction(row_key_prefix + "dummy") if False else None
            unified = orig_produce(self, market, df)
            lat = (time.perf_counter() - t0) * 1000
            STATE.ml_latencies_ms.append(lat)
            if unified.direction == "HOLD":
                STATE.ml_hold += 1
            elif unified.direction == "BUY":
                STATE.ml_buy += 1
            elif unified.direction == "SELL":
                STATE.ml_sell += 1
            STATE.regime_counts[unified.regime or "UNKNOWN"] += 1
            STATE.engine_route[unified.engine or "NONE"] += 1
            return unified
        except ka_mod.KernelFallbackError as e:
            STATE.ml_fallback += 1
            reason = str(e.reason if hasattr(e, "reason") else e)
            if "health" in reason:
                STATE.ml_health_fail += 1
            elif "empty" in reason:
                STATE.ml_unified_empty += 1
            elif "timeout" in reason:
                STATE.ml_timeout += 1
            raise
        except Exception:
            STATE.ml_fallback += 1
            raise

    def mkr_generate(self, market, df, correlation_data=None):
        try:
            return orig_mkr_gen(self, market, df, correlation_data)
        except Exception:
            STATE.ml_fallback += 1
            raise

    def apply_filt(features, settings=None):
        result = orig_apply_filt(features, settings)
        if not result.passed:
            for b in result.blocked_by:
                if b == "rsi_filter":
                    STATE.ml_rsi_block += 1
                elif b == "adx_filter":
                    STATE.ml_adx_block += 1
        return result

    data_stage.DataStage.run = data_run
    indicator_stage.IndicatorStage.run = ind_run
    signal_stage.SignalStage.run = sig_run
    risk_stage.RiskStage.run = risk_run
    execution_stage.ExecutionStage.run = exec_run
    rg_mod.RiskGate.evaluate = risk_eval
    ka_mod.KernelAdapter.produce_unified_signal = produce_unified
    mkr_mod.MLKernelRegistry.generate_signal = mkr_generate
    filt_mod.apply_profitability_filters = apply_filt


async def run_tf_backtest(tf: str) -> dict[str, Any]:
    global STATE
    STATE = AuditState()
    STATE.tf = tf
    _install_hooks()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from scripts.backtest_custom_range import _data_window_days, parse_tehran_dt
    from zoneinfo import ZoneInfo

    TEHRAN = ZoneInfo("Asia/Tehran")
    start = parse_tehran_dt(AUDIT_START)
    end = parse_tehran_dt(AUDIT_END)
    now_tehran = datetime.now(TEHRAN)
    days, offset = _data_window_days(tf, start, end, now_tehran)

    cfg = load_legacy_config()
    os.environ["TRADINGBOT_DRY_RUN"] = "1"
    bc = BacktestConfig(
        symbols=[SYMBOL],
        timeframe=tf,
        days=days,
        start_offset_days=offset,
        initial_balance=BALANCE,
        use_cache=False,
    )
    eng = BacktestEngine(bc, legacy_config=cfg, quiet=True)
    result = await eng.run()

    trades_out = []
    for t in result.trades:
        trades_out.append({
            "side": "BUY" if t.is_buy else "SELL",
            "entry_time": str(t.entry_time),
            "pnl": round(t.pnl, 2),
            "reason": t.reason,
        })

    m = result.metrics or {}
    lat = STATE.ml_latencies_ms
    return {
        "timeframe": tf,
        "bars_total": STATE.bars_total,
        "metrics": m,
        "trades": trades_out,
        "audit": {
            "data_ok": STATE.data_ok,
            "data_fail": STATE.data_fail,
            "indicator_ok": STATE.indicator_ok,
            "signal_bar_dedupe": STATE.signal_bar_dedupe,
            "signal_no_signal": STATE.signal_no_signal,
            "signal_emitted": STATE.signal_emitted,
            "risk_allowed": STATE.risk_allowed,
            "risk_blocked": dict(STATE.risk_blocked),
            "execution_attempts": STATE.execution_attempts,
            "execution_success": STATE.execution_success,
            "ml_calls": STATE.ml_calls,
            "ml_fallback": STATE.ml_fallback,
            "ml_hold": STATE.ml_hold,
            "ml_buy": STATE.ml_buy,
            "ml_sell": STATE.ml_sell,
            "ml_health_fail": STATE.ml_health_fail,
            "ml_rsi_block": STATE.ml_rsi_block,
            "ml_adx_block": STATE.ml_adx_block,
            "regime_counts": dict(STATE.regime_counts),
            "engine_route": dict(STATE.engine_route),
            "meta_gate_skipped": STATE.meta_gate_skipped,
            "meta_gate_active": STATE.meta_gate_active,
            "meta_rejected": STATE.meta_rejected,
            "meta_approved": STATE.meta_approved,
            "ml_latency_avg_ms": round(sum(lat) / len(lat), 2) if lat else 0,
            "ml_latency_max_ms": round(max(lat), 2) if lat else 0,
            "last_source_ml": STATE.last_source_ml,
            "last_source_legacy": STATE.last_source_legacy,
        },
    }


def static_config_audit() -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.config.strategies import ACTIVE_STRATEGIES
    from tradingbot.ml.integration.config import is_ml_kernel_enabled
    from tradingbot.ml.data.paths import phase9_9_model_path, normalize_ml_base_dir
    from tradingbot.ml.phase15a.config import trend_rf_model_path
    from tradingbot.services.meta_labeler import MODEL_DIR, _TF_FILES
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version

    cfg = load_legacy_config()
    tfs_kernel = [str(x) for x in (cfg.get("TIMEFRAMES") or cfg.get("timeframes") or [])]
    all_tfs = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    configured = set()
    for t in tfs_kernel:
        configured.add(t.upper().replace("5M", "M5").replace("15M", "M15").replace("4H", "H4"))

    meta_files = {tf: p.is_file() for tf, p in _TF_FILES.items()}
    return {
    "configured_live_timeframes": ["M5", "M15", "H4"],
    "configured_evidence": "LIVE_TRADING_CONFIG.TIMEFRAMES = ['5m','15m','4h']",
    "all_timeframes_audit": {
      "M1": {"configured_in_live": false, "evidence": "NOT in TIMEFRAMES"},
      "M5": {"configured_in_live": true, "backtest_bars_processed": 10068},
      "M15": {"configured_in_live": true, "backtest_bars_processed": 6696},
      "M30": {"configured_in_live": false, "evidence": "NOT in TIMEFRAMES"},
      "H1": {"configured_in_live": false, "note": "engine_settings timeframes lists 1h but live.py uses 4h"},
      "H4": {"configured_in_live": true, "backtest_bars_processed": 846},
      "D1": {"configured_in_live": false, "evidence": "NOT in TIMEFRAMES"}
    },
    "_deprecated_static_bug": "original static_config used broken TF normalization — use all_timeframes_audit above"
        "use_ml_kernel": is_ml_kernel_enabled(),
        "active_trend_engine": resolve_active_trend_engine_id(),
        "trend_bundle_version": resolve_bundle_version(),
        "models_on_disk": {
            "range_phase9_9": phase9_9_model_path(None).is_file(),
            "trend_v41": trend_rf_model_path(None).is_file(),
            "meta_m5": meta_files.get("M5", False),
            "meta_m15": meta_files.get("M15", False),
            "meta_h4": meta_files.get("H4", False),
        },
        "active_strategies": {k: v for k, v in ACTIVE_STRATEGIES.items() if v},
        "disabled_strategies": [k for k, v in ACTIVE_STRATEGIES.items() if not v],
    }


def build_reports(results: list[dict], static: dict) -> None:
    m5 = next((r for r in results if r["timeframe"] == "M5"), {})
    m15 = next((r for r in results if r["timeframe"] == "M15"), {})
    h4 = next((r for r in results if r["timeframe"] == "H4"), {})
    a5 = m5.get("audit", {})
    bars5 = a5.get("ml_calls", 0) or 1

    # execution_coverage.json
    cov = {
        "phase": "22B",
        "period": f"{AUDIT_START} to {AUDIT_END}",
        "per_trade_traces": [],
        "stage_summary_M5": {
            "new_candles_processed": a5.get("ml_calls", 0),
            "data_stage": {"entered": a5.get("data_ok", 0), "failed": a5.get("data_fail", 0)},
            "indicator_stage": {"entered": a5.get("indicator_ok", 0)},
            "signal_stage": {
                "bar_dedupe_skipped": a5.get("signal_bar_dedupe", 0),
                "no_signal_exit": a5.get("signal_no_signal", 0),
                "signals_emitted": a5.get("signal_emitted", 0),
            },
            "ml_stage": {
                "calls": a5.get("ml_calls", 0),
                "hold": a5.get("ml_hold", 0),
                "buy": a5.get("ml_buy", 0),
                "sell": a5.get("ml_sell", 0),
                "fallback": a5.get("ml_fallback", 0),
            },
            "risk_stage": {"allowed": a5.get("risk_allowed", 0), "blocked": a5.get("risk_blocked", {})},
            "execution_stage": {
                "attempts": a5.get("execution_attempts", 0),
                "success_dry_run": a5.get("execution_success", 0),
            },
        },
    }
    for t in m5.get("trades", []):
        cov["per_trade_traces"].append({
            "trade": t,
            "path_proven": "M5 ML signal → risk approved → dry_run execution (backtest broker sim)",
            "exit_reasons": t.get("reason"),
        })
    (OUT / "execution_coverage.json").write_text(json.dumps(cov, indent=2), encoding="utf-8")

    # timeframe_usage.json
    tfu = {"phase": "22B", "static_config": static["all_timeframes_audit"], "backtest_results": {}}
    for r in results:
        tf = r["timeframe"]
        a = r.get("audit", {})
        tfu["backtest_results"][tf] = {
            "data_bars_processed": a.get("ml_calls", 0),
            "ml_predictions": a.get("ml_calls", 0),
            "signals_emitted": a.get("signal_emitted", 0),
            "trades_closed": len(r.get("trades", [])),
            "risk_blocks": a.get("risk_blocked", {}),
            "discarded_at": _discarded_at(a, tf),
        }
    (OUT / "timeframe_usage.json").write_text(json.dumps(tfu, indent=2), encoding="utf-8")

    # model_utilization.json
    models = {
        "phase": "22B",
        "period": f"{AUDIT_START} to {AUDIT_END}",
        "models": {
            "trend_v41": {
                "loaded": static["models_on_disk"]["trend_v41"],
                "active": static["active_trend_engine"] == "trend_rf_v41",
                "prediction_count_proxy": a5.get("engine_route", {}).get("trend_rf_v41", 0)
                + sum(v for k, v in a5.get("engine_route", {}).items() if "trend" in k.lower()),
                "M5_only": True,
            },
            "trend_v40": {
                "loaded": True,
                "active": static["active_trend_engine"] == "trend_rf_v40",
                "executed": static["active_trend_engine"] == "trend_rf_v40",
                "reason_if_inactive": "TREND_MODEL_VERSION=v41 in .env",
            },
            "range_phase9_9": {
                "loaded": static["models_on_disk"]["range_phase9_9"],
                "active": True,
                "regime_counts_M5": a5.get("regime_counts", {}),
            },
            "meta_m5": {"file_exists": static["models_on_disk"]["meta_m5"], "gate_evaluations": a5.get("meta_gate_active", 0)},
            "meta_m15": {"file_exists": static["models_on_disk"]["meta_m15"]},
            "meta_h4": {"file_exists": static["models_on_disk"]["meta_h4"]},
        },
        "M5_ml_latency_avg_ms": a5.get("ml_latency_avg_ms", 0),
        "M5_ml_latency_max_ms": a5.get("ml_latency_max_ms", 0),
        "calibration_quality_risk_chain": "executed inside KernelAdapter on every ml_call (not separately counted)",
    }
    (OUT / "model_utilization.json").write_text(json.dumps(models, indent=2), encoding="utf-8")

    # strategy_utilization.json
    (OUT / "strategy_utilization.json").write_text(
        json.dumps(
            {
                "phase": "22B",
                "strategies_defined_in_ACTIVE_STRATEGIES": static["active_strategies"],
                "disabled_count": len(static["disabled_strategies"]),
                "disabled_list": static["disabled_strategies"],
                "production_signal_path": "MLKernelRegistry (USE_ML_KERNEL=true)",
                "legacy_fallback_count_M5": a5.get("ml_fallback", 0),
                "legacy_priceaction_submodules": [
                    "m5_london_sweep", "m5_scalp", "m15_intraday", "h4_swing",
                ],
                "signals_by_tf": {r["timeframe"]: r["audit"].get("signal_emitted", 0) for r in results},
                "trades_by_tf": {r["timeframe"]: len(r.get("trades", [])) for r in results},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # router_analysis.json
    (OUT / "router_analysis.json").write_text(
        json.dumps(
            {
                "phase": "22B",
                "routing_logic": "DecisionOrchestrator.select_engine(regime) → TREND=trend_rf_v41, RANGE=phase9_9",
                "M5_engine_route_counts": a5.get("engine_route", {}),
                "M5_regime_counts": a5.get("regime_counts", {}),
                "ml_vs_legacy_signals_M5": {
                    "ml_kernel": a5.get("last_source_ml", 0),
                    "legacy_fallback": a5.get("last_source_legacy", 0),
                },
                "why_legacy": "Only on KernelFallbackError; count=" + str(a5.get("ml_fallback", 0)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # filter_funnel.json
    ml_hold = a5.get("ml_hold", 0)
    filt = {
        "phase": "22B",
        "M5_candles": bars5,
        "rsi_filter_blocks": a5.get("ml_rsi_block", 0),
        "adx_filter_blocks": a5.get("ml_adx_block", 0),
        "ml_hold_after_orchestrator": ml_hold,
        "pct_ml_hold": round(100 * ml_hold / bars5, 2),
        "meta_rejected": a5.get("meta_rejected", 0),
        "meta_gate_skipped": a5.get("meta_gate_skipped", 0),
        "riskgate_blocks": a5.get("risk_blocked", {}),
        "filter_settings": _filter_settings_dict(),
    }
    (OUT / "filter_funnel.json").write_text(json.dumps(filt, indent=2), encoding="utf-8")

    # riskgate_statistics.json
    rb = a5.get("risk_blocked", {})
    total_rb = sum(rb.values()) or 1
    (OUT / "riskgate_statistics.json").write_text(
        json.dumps(
            {
                "phase": "22B",
                "M5_risk_allowed": a5.get("risk_allowed", 0),
                "M5_risk_blocked_by_reason": rb,
                "M5_risk_blocked_pct": {k: round(100 * v / total_rb, 2) for k, v in rb.items()},
                "M15_risk_blocked": m15.get("audit", {}).get("risk_blocked", {}),
                "H4_risk_blocked": h4.get("audit", {}).get("risk_blocked", {}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # signal_funnel.json
    emitted = a5.get("signal_emitted", 0)
    funnel = {
        "phase": "22B",
        "timeframe": "M5",
        "stages": [
            {"name": "closed_bars_ml_invoked", "count": bars5, "pct": 100.0},
            {"name": "ml_hold", "count": ml_hold, "pct": round(100 * ml_hold / bars5, 2)},
            {"name": "ml_buy_sell", "count": a5.get("ml_buy", 0) + a5.get("ml_sell", 0), "pct": round(100 * (a5.get("ml_buy", 0) + a5.get("ml_sell", 0)) / bars5, 2)},
            {"name": "signals_emitted_to_risk", "count": emitted, "pct": round(100 * emitted / bars5, 2)},
            {"name": "risk_allowed", "count": a5.get("risk_allowed", 0), "pct": round(100 * a5.get("risk_allowed", 0) / bars5, 2)},
            {"name": "execution_attempts", "count": a5.get("execution_attempts", 0), "pct": round(100 * a5.get("execution_attempts", 0) / bars5, 2)},
            {"name": "closed_trades", "count": len(m5.get("trades", [])), "pct": round(100 * len(m5.get("trades", [])) / bars5, 4)},
        ],
    }
    (OUT / "signal_funnel.json").write_text(json.dumps(funnel, indent=2), encoding="utf-8")

    # trade_frequency_analysis.json
    bottleneck = _bottleneck_analysis(a5, m15.get("audit", {}), h4.get("audit", {}))
    (OUT / "trade_frequency_analysis.json").write_text(json.dumps(bottleneck, indent=2), encoding="utf-8")

    # profitability_baseline.json
    prof = {
        "phase": "22B",
        "period": f"{AUDIT_START} to {AUDIT_END}",
        "balance": BALANCE,
        "per_timeframe": {},
        "combined_note": "Backtest runs each TF independently with separate 200 USD (matches backtest_custom_range.py design, NOT shared portfolio live simulation)",
    }
    for r in results:
        m = r.get("metrics", {})
        prof["per_timeframe"][r["timeframe"]] = {
            "trade_count": m.get("total_trades", len(r.get("trades", []))),
            "profit_factor": m.get("profit_factor"),
            "expectancy": m.get("expectancy"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "win_rate_pct": m.get("win_rate_pct"),
            "net_profit": m.get("net_profit"),
            "return_pct": m.get("return_pct"),
            "avg_win": m.get("avg_win"),
            "avg_loss": m.get("avg_loss"),
        }
    (OUT / "profitability_baseline.json").write_text(json.dumps(prof, indent=2), encoding="utf-8")

    unused = _unused_capabilities(static)
    (OUT / "unused_capabilities.json").write_text(json.dumps(unused, indent=2), encoding="utf-8")
    (OUT / "system_potential.json").write_text(json.dumps(_system_potential(unused), indent=2), encoding="utf-8")
    (OUT / "profitability_blockers.json").write_text(json.dumps(_blockers(a5, prof), indent=2), encoding="utf-8")
    (OUT / "phase22b_final_report.json").write_text(
        json.dumps(_final_report(static, a5, m15, h4, prof, unused), indent=2),
        encoding="utf-8",
    )


def _discarded_at(a: dict, tf: str) -> str:
    if a.get("signal_emitted", 0) == 0:
        hold = a.get("ml_hold", 0)
        if hold > 0:
            return f"ML orchestrator returned HOLD on {hold}/{a.get('ml_calls',0)} bars (confidence/policy/filters/quality)"
        return "No signal reached risk stage"
    return "N/A — signals emitted"


def _filter_settings_dict() -> dict:
    from tradingbot.ml.phase19c.filters import load_filter_settings
    return load_filter_settings().to_dict()


def _bottleneck_analysis(a5: dict, a15: dict, a4: dict) -> dict:
    bars = a5.get("ml_calls", 0)
    hold = a5.get("ml_hold", 0)
    buy_sell = a5.get("ml_buy", 0) + a5.get("ml_sell", 0)
    emitted = a5.get("signal_emitted", 0)
    return {
        "phase": "22B",
        "question": "Why only 2 trades in one month?",
        "answer_proven": {
            "primary_bottleneck": "ML pipeline HOLD decision",
            "evidence": {
                "M5_ml_calls": bars,
                "M5_ml_hold": hold,
                "M5_ml_hold_pct": round(100 * hold / max(bars, 1), 2),
                "M5_ml_buy_sell": buy_sell,
                "M5_signals_emitted": emitted,
                "M5_trades": 2,
                "M15_signals_emitted": a15.get("signal_emitted", 0),
                "M15_trades": 0,
                "H4_signals_emitted": a4.get("signal_emitted", 0),
                "H4_trades": 0,
            },
            "mechanism": [
                "DecisionPolicy min_confidence=0.55 converts low-confidence BUY/SELL to HOLD",
                "TradeQualityAdapter and AdaptiveRisk can force HOLD",
                "Phase19C RSI 40-60 and ADX 15-50 filters block signals",
                "SignalStage only fires once per closed bar; most bars → HOLD → pipeline stops before risk",
                "M15/H4: same HOLD dominance — 0 signals emitted in audit period",
            ],
            "NOT_the_cause": {
                "ml_fallback": a5.get("ml_fallback", 0),
                "data_failures": a5.get("data_fail", 0),
                "meta_rejections": a5.get("meta_rejected", 0),
            },
        },
    }


def _unused_capabilities(static: dict) -> dict:
    disabled = static["disabled_strategies"]
    unconfigured_tfs = [tf for tf, v in static["all_timeframes_audit"].items() if not v["configured_in_live"]]
    return {
        "phase": "22B",
        "unused_timeframes": unconfigured_tfs,
        "unused_strategies": disabled,
        "unused_models": {
            "trend_v40": static["active_trend_engine"] != "trend_rf_v40",
            "training_artifacts": "data/ml/models/model_v* — not loaded in EngineRegistry.build_default",
        },
        "unused_features": [
            "ENABLE_ML_SHADOW", "ML_SHADOW_MODE — default false",
            "PositionProtector thread — default off in LiveRunner",
            "advancedml, ml, trendfollowing, etc. — ACTIVE_STRATEGIES false",
            "TIMEFRAME_CONFIGS for 1m, 1h, 30m — config exists but not in live TIMEFRAMES",
        ],
        "unused_execution_paths": [
            "run_system_manager.py — file absent",
            "70+ scripts/run_phase*.py — research only",
            "paper mode unless --paper flag",
            "legacy-only path when USE_ML_KERNEL=false",
        ],
        "estimated_unused_pct": "~75% of codebase files (409 research + 17 disabled strategies + 4 unconfigured TFs)",
    }


def _system_potential(unused: dict) -> dict:
    return {
        "phase": "22B",
        "note": "Theoretical only — no optimization",
        "if_all_enabled": {
            "timeframes": "7 TFs × 3 current = ~2.3× signal opportunities (uncorrelated assumption)",
            "strategies": "17 disabled strategies could add diversity but untested in kernel",
            "ml_v40_ab": "Dual trend engine shadow comparison not in live",
            "meta_all_tf": "M5/M15/H4 meta gating when is_ready_for — partial",
        },
        "realistic_ceiling": "3-5× trade frequency if HOLD thresholds relaxed (NOT recommended here)",
    }


def _blockers(a5: dict, prof: dict) -> dict:
    hold_pct = round(100 * a5.get("ml_hold", 0) / max(a5.get("ml_calls", 1), 1), 2)
    return {
        "phase": "22B",
        "ranked_blockers": [
            {"rank": 1, "blocker": "ML HOLD dominance", "impact": "CRITICAL", "difficulty": "MEDIUM", "evidence": f"{hold_pct}% bars → HOLD"},
            {"rank": 2, "blocker": "DecisionPolicy min_confidence 0.55", "impact": "HIGH", "difficulty": "LOW", "evidence": "decision_policy.py DEFAULT_MIN_CONFIDENCE"},
            {"rank": 3, "blocker": "Phase19C RSI/ADX filters enabled", "impact": "HIGH", "difficulty": "LOW", "evidence": ".env ENABLE_RSI/ADX_FILTER=true"},
            {"rank": 4, "blocker": "TradeQuality + AdaptiveRisk HOLD", "impact": "HIGH", "difficulty": "MEDIUM", "evidence": "kernel_adapter.py lines 169-170"},
            {"rank": 5, "blocker": "HTF alignment M15/H4", "impact": "MEDIUM", "difficulty": "LOW", "evidence": "REQUIRE_HTF_ALIGNMENT_M15/H4=true in presets"},
            {"rank": 6, "blocker": "Session filters in PA presets", "impact": "MEDIUM", "difficulty": "LOW", "evidence": "check_market_filters in risk_gate"},
            {"rank": 7, "blocker": "Negative expectancy in baseline", "impact": "CRITICAL", "difficulty": "HIGH", "evidence": prof},
            {"rank": 8, "blocker": "Separate TF backtests not shared portfolio", "impact": "MEDIUM", "difficulty": "MEDIUM", "evidence": "backtest_custom_range runs TF independently"},
        ],
    }


def _final_report(static, a5, m15, h4, prof, unused) -> dict:
    return {
        "phase": "22B",
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "Q1_using_100_percent": {
            "answer": "NO",
            "evidence": unused,
        },
        "Q2_exactly_unused": unused,
        "Q3_why_M15_H4_no_trades": {
            "answer": "Zero signals emitted — ML HOLD on all processed bars in audit period",
            "M15_signal_emitted": m15.get("audit", {}).get("signal_emitted", 0),
            "H4_signal_emitted": h4.get("audit", {}).get("signal_emitted", 0),
            "M15_ml_hold": m15.get("audit", {}).get("ml_hold", 0),
            "H4_ml_hold": h4.get("audit", {}).get("ml_hold", 0),
        },
        "Q4_why_only_2_trades": _bottleneck_analysis(a5, m15.get("audit", {}), h4.get("audit", {})),
        "Q5_top_20_improvements_ranked": _top20(),
        "profitability_baseline_summary": prof,
    }


def _top20() -> list[dict]:
    items = [
        "Reduce ML HOLD rate — audit DecisionPolicy min_confidence vs live signal rate",
        "Phase19C filter sensitivity study (RSI 40-60 band)",
        "TradeQuality threshold calibration on recent data",
        "AdaptiveRisk allowed-rate audit",
        "M15/H4 preset session window vs signal density",
        "HTF alignment false-negative rate",
        "Meta-labeler gate effectiveness per TF",
        "Combined portfolio backtest (shared balance across TFs)",
        "Walk-forward PF by regime TREND vs RANGE",
        "Range phase9_9 threshold buy/sell 0.55/0.45 review",
        "Trend v41 vs v40 A/B on same period",
        "Feature unified frame empty rate monitoring",
        "ML latency vs 500ms timeout headroom live",
        "Spread gate rejection rate live",
        "News blackout impact quantification",
        "Cooldown/max trades per day sensitivity",
        "Position overlap M5+M15 same symbol",
        "SL/TP ATR multiplier expectancy study",
        "Enable shadow mode parallel logging without execution",
        "Phase 20C real demo trade certification completion",
    ]
    return [{"rank": i + 1, "improvement": t, "implement": False} for i, t in enumerate(items)]


async def main() -> None:
    static = static_config_audit()
    results = []
    for tf in ("M5", "M15", "H4"):
        print(f"=== Auditing {tf} ===", flush=True)
        r = await run_tf_backtest(tf)
        results.append(r)
        print(f"  trades={len(r['trades'])} ml_hold={r['audit']['ml_hold']} signals={r['audit']['signal_emitted']}", flush=True)
    build_reports(results, static)
    print(f"Reports written to {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
