#!/usr/bin/env python3
"""7-day adaptive regime live-truth backtest + rejection funnel analysis."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Force live-equivalent engine flags before imports
os.environ.setdefault("USE_ML_KERNEL", "false")
os.environ.setdefault("ADAPTIVE_REGIME_ENABLED", "true")
os.environ.setdefault("ADAPTIVE_CONFLUENCE_ONLY", "true")

import pandas as pd

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.engine import BacktestEngine
from tradingbot.config.live import get_live_config
from tradingbot.services.rejection_events import (
    enable_counter_mode,
    get_rejection_counts,
    reset_rejection_counts,
)
from tradingbot.services.runtime_truth import collect_runtime_truth
from tradingbot.strategies.adaptive_regime import (
    evaluate_adaptive_at_index,
    prepare_adaptive_frame,
)


def _scan_signal_funnel(frame: pd.DataFrame, warmup: int) -> dict[str, int]:
    reset_rejection_counts()
    enable_counter_mode(True)
    signals = 0
    for idx in range(warmup, len(frame)):
        sig = evaluate_adaptive_at_index(frame, idx, log_rejections=True)
        if sig is not None:
            signals += 1
    counts = get_rejection_counts()
    enable_counter_mode(False)
    return {
        "total_signals_generated": signals,
        "blocked_by_session": counts.get("SESSION", 0),
        "blocked_by_regime": counts.get("REGIME", 0),
        "blocked_by_confluence": counts.get("CONFLUENCE", 0),
        "blocked_by_h1_alignment": counts.get("H1_ALIGN", 0),
        "blocked_by_ema_sep": counts.get("EMA_SEP", 0),
        "bars_scanned": len(frame) - warmup,
    }


def _avg_hold_hours(trades: list, timeframe: str = "M5") -> float:
    bar_min = {"M5": 5, "M15": 15, "H4": 240}.get(timeframe.upper(), 5)
    durations: list[float] = []
    for t in trades:
        if hasattr(t, "entry_time") and hasattr(t, "exit_time"):
            try:
                delta = t.exit_time - t.entry_time
                if hasattr(delta, "total_seconds"):
                    durations.append(delta.total_seconds() / 3600)
                    continue
            except Exception:
                pass
        if hasattr(t, "exit_index") and hasattr(t, "entry_index"):
            bars = int(t.exit_index) - int(t.entry_index)
            if bars > 0:
                durations.append(bars * bar_min / 60)
    return round(sum(durations) / len(durations), 2) if durations else 0.0


async def run_analysis(*, days: int = 7, initial_balance: float = 200.0) -> dict:
    live = get_live_config()
    legacy = load_legacy_config()
    truth = collect_runtime_truth(legacy_config=legacy)

    cfg = BacktestConfig(
        symbols=["XAUUSD"],
        timeframe="M5",
        days=days,
        warmup=80,
        initial_balance=initial_balance,
        risk_per_trade=float(live.get("RISK_PER_TRADE", 0.005)),
        max_trades_per_day=int(live.get("VOL_REGIME_MAX_TRADES_PER_DAY", 3)),
        cooldown_bars=int(live.get("VOL_REGIME_COOLDOWN_BARS", 12)),
        max_open_positions_total=int(live.get("VOL_REGIME_MAX_CONCURRENT", 1)),
        max_positions_per_symbol=int(live.get("VOL_REGIME_MAX_CONCURRENT", 1)),
        use_news_filter=bool(live.get("USE_NEWS_FILTER", True)),
        enable_eod_close=bool(live.get("EOD_CLOSE_ENABLED", True)),
        eod_hour=int(live.get("EOD_HOUR", 23)),
        eod_minute=int(live.get("EOD_MINUTE", 55)),
        use_cache=True,
    )

    engine = BacktestEngine(cfg, legacy, quiet=True)
    length = _load_with_fallback(engine, cfg, days)
    if length <= cfg.warmup + 1:
        raise RuntimeError(f"Insufficient data: {length} bars (need MT5 or parquet cache)")

    raw = engine.data_source.frame("XAUUSD")
    if raw is None or raw.empty:
        raise RuntimeError("No XAUUSD frame loaded")
    frame = prepare_adaptive_frame(raw.copy())
    funnel = _scan_signal_funnel(frame, cfg.warmup)

    result = await engine.run()
    metrics = result.metrics or {}
    trades = result.trades

    executed = int(metrics.get("total_trades", 0))
    signals = funnel["total_signals_generated"]
    estimated_risk_blocks = max(0, signals - executed)

    pf = metrics.get("profit_factor", 0)
    pf_val = float("inf") if pf == "inf" else float(pf)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "initial_balance": initial_balance,
        "runtime_truth": truth,
        "funnel": funnel,
        "blocked_by_riskgate_estimated": estimated_risk_blocks,
        "executed_trades": executed,
        "profit_factor": pf_val,
        "expectancy": metrics.get("expectancy", 0),
        "net_profit": metrics.get("net_profit", 0),
        "return_pct": metrics.get("return_pct", 0),
        "win_rate_pct": metrics.get("win_rate_pct", 0),
        "average_hold_hours": _avg_hold_hours(trades, cfg.timeframe),
        "exit_reasons": metrics.get("exit_reasons", {}),
        "bars_total": length,
        "data_source_note": getattr(engine.data_source, "_load_note", "cache_or_mt5"),
    }


def _load_with_fallback(engine: BacktestEngine, cfg: BacktestConfig, days: int) -> int:
    """Load backtest data from cache; fall back to longer cache or data/*.parquet."""
    length = engine.data_source.load()
    if length > cfg.warmup + 1:
        engine.data_source._load_note = "primary_cache"  # noqa: SLF001
        return length

    root = ROOT / "data"
    fallbacks = [
        root / "backtest" / f"XAUUSD_M5_{days}d.parquet",
        root / "backtest" / "XAUUSD_M5_14d.parquet",
        root / "backtest" / "XAUUSD_M5_21d.parquet",
        root / "XAUUSD_5m.parquet",
    ]
    bpd = 288  # M5 bars per day
    window = days * bpd

    for path in fallbacks:
        if not path.is_file():
            continue
        try:
            df = pd.read_parquet(path)
            if df.empty:
                continue
            if len(df) > window:
                df = df.iloc[-window:].copy()
            enriched = engine.data_source._indicators.enrich_for_market(  # noqa: SLF001
                df, cfg.timeframe, "XAUUSD"
            )
            enriched = enriched.dropna(subset=["open", "high", "low", "close"])
            injected = engine.data_source.inject({"XAUUSD": enriched})
            if injected > cfg.warmup + 1:
                engine.data_source._load_note = f"fallback:{path.name}"  # noqa: SLF001
                return injected
        except Exception:
            continue
    engine.data_source._load_note = "none"  # noqa: SLF001
    return length


def write_markdown(report: dict, path: Path) -> None:
    f = report["funnel"]
    truth = report["runtime_truth"]
    lines = [
        "# Adaptive Regime Live Truth — 7-Day Backtest",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Window:** {report['window_days']} days | **Initial balance:** ${report['initial_balance']}",
        f"**Data source:** {report.get('data_source_note', 'unknown')}",
        "",
        "## Active configuration (from runtime truth)",
        "",
        f"- Engine: **{truth['active_strategy_engine']}**",
        f"- ADAPTIVE_CONFLUENCE_ONLY: **{truth['ADAPTIVE_CONFLUENCE_ONLY']}**",
        f"- Session: **{', '.join(truth['session_window_utc'])}**",
        f"- Cooldown: **{truth['cooldown_bars']}** bars | Max trades/day: **{truth['max_trades_per_day']}**",
        "",
        "## Signal funnel (bar scan)",
        "",
        f"| Metric | Count |",
        f"|--------|------:|",
        f"| Bars scanned | {f['bars_scanned']} |",
        f"| **total_signals_generated** | **{f['total_signals_generated']}** |",
        f"| blocked_by_session | {f['blocked_by_session']} |",
        f"| blocked_by_regime | {f['blocked_by_regime']} |",
        f"| blocked_by_confluence | {f['blocked_by_confluence']} |",
        f"| blocked_by_h1_alignment | {f['blocked_by_h1_alignment']} |",
        f"| blocked_by_ema_sep | {f['blocked_by_ema_sep']} |",
        f"| blocked_by_riskgate (estimated) | {report['blocked_by_riskgate_estimated']} |",
        "",
        "## Execution results",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| executed_trades | {report['executed_trades']} |",
        f"| profit_factor | {report['profit_factor']} |",
        f"| expectancy | {report['expectancy']} |",
        f"| net_profit | {report['net_profit']} |",
        f"| return_pct | {report['return_pct']}% |",
        f"| win_rate_pct | {report['win_rate_pct']}% |",
        f"| average_hold_hours | {report['average_hold_hours']} |",
        "",
        "## Exit reasons",
        "",
        "```json",
        __import__("json").dumps(report["exit_reasons"], indent=2),
        "```",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    report = asyncio.run(run_analysis(days=7, initial_balance=200.0))
    out = ROOT / "docs" / "adaptive_regime_live_truth_7d.md"
    write_markdown(report, out)
    print(f"Report written: {out}")
    print(f"Signals: {report['funnel']['total_signals_generated']} | Trades: {report['executed_trades']} | PF: {report['profit_factor']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
