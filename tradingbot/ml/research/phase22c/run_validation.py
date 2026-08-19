#!/usr/bin/env python3
"""Phase 22C — multi-timeframe validation backtests + hold-chain report."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = Path(__file__).resolve().parent
AUDIT_START = "2026-06-04 00:00"
AUDIT_END = "2026-07-04 23:59"
BALANCE = 200.0
SYMBOL = "XAUUSD"
TIMEFRAMES = ("M5", "M15", "H4")


async def _run_tf(tf: str) -> dict:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.ml.research.phase22c.hold_chain import get_hold_chain, reset_hold_chain
    from scripts.backtest_custom_range import _data_window_days, parse_tehran_dt

    reset_hold_chain()
    TEHRAN = ZoneInfo("Asia/Tehran")
    start = parse_tehran_dt(AUDIT_START)
    end = parse_tehran_dt(AUDIT_END)
    now_tehran = datetime.now(TEHRAN)
    days, offset = _data_window_days(tf, start, end, now_tehran)

    cfg = load_legacy_config()
    os.environ["TRADINGBOT_DRY_RUN"] = "1"
    os.environ.setdefault("PHASE22C_ENABLED", "true")
    bc = BacktestConfig(
        symbols=[SYMBOL],
        timeframe=tf,
        days=days,
        start_offset_days=offset,
        initial_balance=BALANCE,
        use_cache=False,
    )
    t0 = time.perf_counter()
    eng = BacktestEngine(bc, legacy_config=cfg, quiet=True)
    result = await eng.run()
    elapsed = time.perf_counter() - t0
    m = result.metrics or {}
    chain = get_hold_chain().snapshot()
    buys = sum(1 for t in result.trades if t.is_buy)
    sells = len(result.trades) - buys
    return {
        "timeframe": tf,
        "elapsed_sec": round(elapsed, 1),
        "bars": len(result.equity_curve),
        "trades": len(result.trades),
        "buy_trades": buys,
        "sell_trades": sells,
        "net_profit": round(result.final_balance - result.initial_balance, 2),
        "profit_factor": m.get("profit_factor"),
        "expectancy": m.get("expectancy"),
        "max_drawdown_pct": m.get("max_drawdown_pct"),
        "win_rate_pct": m.get("win_rate_pct"),
        "hold_chain": chain,
    }


async def main() -> int:
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg = load_phase22c_config()
    results: dict = {
        "phase": "22C",
        "period": f"{AUDIT_START} → {AUDIT_END}",
        "balance": BALANCE,
        "config": cfg.to_dict(),
        "per_timeframe": {},
        "targets": {
            "profit_factor_min": 1.3,
            "expectancy_min_r": 0.15,
        },
    }
    for tf in TIMEFRAMES:
        print(f"Running {tf}...", flush=True)
        results["per_timeframe"][tf] = await _run_tf(tf)
        hc = results["per_timeframe"][tf]["hold_chain"]
        print(
            f"  {tf}: trades={results['per_timeframe'][tf]['trades']} "
            f"BUY={results['per_timeframe'][tf]['buy_trades']} "
            f"SELL={results['per_timeframe'][tf]['sell_trades']} "
            f"ML signals={hc.get('ml_signals')} "
            f"decision_hold={hc['ml_hold_stages']['decision_hold']}",
            flush=True,
        )

    pf_ok = all(
        (results["per_timeframe"][tf].get("profit_factor") or 0) >= 1.3
        for tf in TIMEFRAMES
        if results["per_timeframe"][tf]["trades"] >= 5
    )
    m5 = results["per_timeframe"]["M5"]["hold_chain"]
    buy_sig = m5.get("buy_emitted", 0)
    sell_sig = m5.get("sell_emitted", 0)
    results["verdict"] = {
        "buy_sell_balance": buy_sig > 0 and sell_sig > 0,
        "m15_signals": results["per_timeframe"]["M15"]["hold_chain"].get("ml_signals", 0) > 0,
        "h4_signals": results["per_timeframe"]["H4"]["hold_chain"].get("ml_signals", 0) > 0,
        "hold_rate_m5_pct": round(
            100.0 * m5["ml_hold_stages"]["decision_hold"] / max(1, m5["bars_evaluated"]),
            2,
        ),
        "pf_target_met": pf_ok,
    }
    out_path = OUT / "phase22c_final_report.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    get_hold_chain().write_json(OUT / "hold_chain_combined.json")
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
