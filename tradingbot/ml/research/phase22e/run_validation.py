#!/usr/bin/env python3
"""Phase 22E — full production validation and profitability certification."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = Path(__file__).resolve().parent

from tradingbot.backtest.models import ClosedTrade  # noqa: E402
from tradingbot.ml.research.phase22e.certification import assess_live_readiness, build_final_report  # noqa: E402
from tradingbot.ml.research.phase22e.config import (  # noqa: E402
    TIMEFRAMES,
    WINDOW_LABELS,
    compute_windows,
    configure_production_env,
)
from tradingbot.ml.research.phase22e.delta import build_delta_report  # noqa: E402
from tradingbot.ml.research.phase22e.distribution import compute_trade_distribution  # noqa: E402
from tradingbot.ml.research.phase22e.montecarlo import run_monte_carlo  # noqa: E402
from tradingbot.ml.research.phase22e.portfolio import run_portfolio_backtest  # noqa: E402
from tradingbot.ml.research.phase22e.runner import run_production_backtest  # noqa: E402
from tradingbot.ml.research.phase22e.stress import run_stress_suite, stress_from_trades  # noqa: E402
from tradingbot.ml.research.phase22e.walkforward import run_walkforward  # noqa: E402


def _write(name: str, payload: dict) -> Path:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {path.name}", flush=True)
    return path


def _rebuild_trades(trades_raw: list[dict]) -> list[ClosedTrade]:
    out: list[ClosedTrade] = []
    for t in trades_raw:
        out.append(
            ClosedTrade(
                symbol="XAUUSD",
                is_buy=t["side"] == "BUY",
                entry_price=0.0,
                exit_price=0.0,
                volume=0.01,
                entry_time=datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
                if "T" in t["entry_time"]
                else datetime.strptime(t["entry_time"][:19], "%Y-%m-%d %H:%M:%S"),
                exit_time=datetime.now(timezone.utc),
                pnl=float(t["pnl"]),
                reason=t.get("reason", ""),
                strategy=t.get("strategy", ""),
                r_multiple=float(t.get("r_multiple", 0)),
            )
        )
    return out


def _summarize_tf_results(tf: str, windows: dict[str, dict]) -> dict:
    primary = windows.get("1m") or windows.get("3m") or next(iter(windows.values()))
    audit = primary.get("audit") or {}
    m = primary.get("metrics") or primary.get("metrics_window") or {}
    return {
        "timeframe": tf,
        "windows": windows,
        "primary_window": primary.get("window"),
        "summary": {
            "bars": audit.get("bars", 0),
            "buy_signals": audit.get("buy_signals", 0),
            "sell_signals": audit.get("sell_signals", 0),
            "hold_signals": audit.get("hold_signals", 0),
            "trend_trades": audit.get("trend_trades", 0),
            "range_trades": audit.get("range_trades", 0),
            "signals_blocked": audit.get("signals_blocked", 0),
            "trades_executed": audit.get("trades_executed", 0),
            "profit_factor": m.get("profit_factor"),
            "expectancy": m.get("expectancy"),
            "net_profit": m.get("net_profit"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
        },
    }


def _build_profitability_summary(per_tf: dict[str, dict]) -> dict:
    activity = {}
    cert_flags = []
    for tf in TIMEFRAMES:
        win = per_tf[tf]["windows"]
        ref = win.get("1y") or win.get("6m") or win.get("3m") or win.get("1m")
        audit = ref.get("audit") or {}
        m = ref.get("metrics") or ref.get("metrics_window") or {}
        activity[f"{tf.lower()}_active"] = (
            audit.get("trades_executed", 0) > 0
            or audit.get("buy_signals", 0) + audit.get("sell_signals", 0) > 0
        )
        c = m.get("certification") or {}
        cert_flags.append(c)

    any_cert = cert_flags[0] if cert_flags else {}
    return {
        "phase": "22E",
        "per_timeframe": {tf: per_tf[tf]["summary"] for tf in TIMEFRAMES},
        "all_windows": {tf: per_tf[tf]["windows"] for tf in TIMEFRAMES},
        "activity": {
            **activity,
            "buy_active": any(
                per_tf[tf]["summary"].get("buy_signals", 0) > 0
                or per_tf[tf]["summary"].get("trend_trades", 0) > 0
                for tf in TIMEFRAMES
            ),
            "sell_active": any(per_tf[tf]["summary"].get("sell_signals", 0) > 0 for tf in TIMEFRAMES),
        },
        "certification_summary": {
            "pf_target_met": any(c.get("pf_target_met") for c in cert_flags if c),
            "positive_expectancy": any(c.get("positive_expectancy") for c in cert_flags if c),
            "max_dd_within_limit": all(c.get("max_dd_within_limit", True) for c in cert_flags if c),
        },
    }


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 22E production validation")
    parser.add_argument("--windows", default="all", help="Comma list: 1m,3m,6m,1y,3y or all")
    parser.add_argument("--quick", action="store_true", help="Run 1m window only")
    parser.add_argument("--skip-portfolio", action="store_true")
    parser.add_argument("--skip-stress", action="store_true")
    parser.add_argument("--skip-mc", action="store_true")
    parser.add_argument("--skip-wf", action="store_true")
    args = parser.parse_args(argv)

    configure_production_env()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.quick:
        labels = ["1m"]
    elif args.windows == "all":
        labels = list(WINDOW_LABELS)
    else:
        labels = [x.strip() for x in args.windows.split(",") if x.strip()]

    windows = [w for w in compute_windows() if w.label in labels]
    print(f"Phase 22E | windows={labels} | output={OUT}", flush=True)

    per_tf: dict[str, dict] = {}
    all_trades_by_tf: dict[str, list[ClosedTrade]] = {tf: [] for tf in TIMEFRAMES}
    t_total = time.perf_counter()

    for tf in TIMEFRAMES:
        print(f"\n=== {tf} backtests ===", flush=True)
        win_results: dict[str, dict] = {}
        for window in windows:
            print(f"  {tf} {window.label} ({window.start.date()} -> {window.end.date()})...", flush=True)
            try:
                result = await run_production_backtest(tf, window)
                win_results[window.label] = result
                raw = result.get("trades_window") or result.get("trades_all") or []
                all_trades_by_tf[tf].extend(_rebuild_trades(raw))
                m = result.get("metrics") or result["metrics_window"]
                print(
                    f"    trades={result['window_trades_count']} "
                    f"PF={m.get('profit_factor')} exp={m.get('expectancy')} "
                    f"BUY sig={result['audit'].get('buy_signals')} "
                    f"SELL sig={result['audit'].get('sell_signals')} "
                    f"({result['elapsed_sec']}s)",
                    flush=True,
                )
            except RuntimeError as exc:
                print(f"    SKIP: {exc}", flush=True)
                win_results[window.label] = {"error": str(exc), "window": window.to_dict()}
        per_tf[tf] = _summarize_tf_results(tf, win_results)

    _write("backtest_m5.json", per_tf["M5"])
    _write("backtest_m15.json", per_tf["M15"])
    _write("backtest_h4.json", per_tf["H4"])

    profitability = _build_profitability_summary(per_tf)
    _write("profitability_summary.json", profitability)

    distribution = {
        "phase": "22E",
        "per_timeframe": {
            tf: compute_trade_distribution(all_trades_by_tf[tf], label=tf) for tf in TIMEFRAMES
        },
    }
    _write("trade_distribution.json", distribution)

    portfolio_window = next((w for w in windows if w.label == "1y"), windows[-1])
    if args.skip_portfolio:
        portfolio = {"skipped": True, "window": portfolio_window.to_dict()}
    else:
        print(f"\n=== Portfolio ({portfolio_window.label}) ===", flush=True)
        try:
            portfolio = await run_portfolio_backtest(portfolio_window)
            print(
                f"  trades={portfolio['trades']} net={portfolio['metrics'].get('net_profit')} "
                f"PF={portfolio['metrics'].get('profit_factor')} ({portfolio['elapsed_sec']}s)",
                flush=True,
            )
        except Exception as exc:
            portfolio = {"error": str(exc), "window": portfolio_window.to_dict()}
            print(f"  portfolio FAILED: {exc}", flush=True)
    _write("portfolio_backtest.json", portfolio)

    wf_trades = all_trades_by_tf["M5"]
    if len(wf_trades) < 10:
        for tf in TIMEFRAMES:
            wf_trades = wf_trades + all_trades_by_tf[tf]
    walkforward = {"skipped": True} if args.skip_wf else run_walkforward(wf_trades)
    _write("walkforward_results.json", walkforward)

    montecarlo = {"skipped": True} if args.skip_mc else run_monte_carlo(wf_trades)
    _write("montecarlo_results.json", montecarlo)

    stress_primary = next((w for w in windows if w.label == "1m"), windows[0])
    if args.skip_stress:
        stress = {"skipped": True}
    else:
        print(f"\n=== Stress (M5 {stress_primary.label}) ===", flush=True)
        stress = await run_stress_suite("M5", stress_primary)
        stress["trade_regime_segments"] = stress_from_trades(wf_trades, stress_primary)
    _write("stress_test_results.json", stress)

    delta = build_delta_report(profitability)
    _write("phase22d_vs_phase22e.json", delta)

    live_readiness = assess_live_readiness(
        profitability, portfolio, walkforward, montecarlo, stress, delta
    )
    _write("live_readiness.json", live_readiness)

    final = build_final_report(
        profitability=profitability,
        portfolio=portfolio,
        distribution=distribution,
        walkforward=walkforward,
        montecarlo=montecarlo,
        stress=stress,
        delta=delta,
        live_readiness=live_readiness,
        backtests={tf: per_tf[tf]["windows"] for tf in TIMEFRAMES},
    )
    final["elapsed_total_sec"] = round(time.perf_counter() - t_total, 1)
    _write("phase22e_final_report.json", final)

    print(f"\nPhase 22E complete | verdict={live_readiness['verdict']} | {final['elapsed_total_sec']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
