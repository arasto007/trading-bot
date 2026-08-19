#!/usr/bin/env python3
"""30-day backtest with sub-strategy breakdown."""
from __future__ import annotations

import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()
os.environ.setdefault("USE_ML_KERNEL", "false")
os.environ.setdefault("ADAPTIVE_REGIME_ENABLED", "true")


def make_config(days: int = 30, balance: float = 200.0, offset_days: int = 0):
    from tradingbot.backtest.config import BacktestConfig

    return BacktestConfig(
        symbols=["XAUUSD"],
        timeframe="M5",
        days=days,
        start_offset_days=offset_days,
        warmup=500,
        initial_balance=balance,
        risk_per_trade=0.01,
        max_trades_per_day=3,
        cooldown_bars=12,
        require_htf_alignment_m5=False,
        use_meta_labeler=False,
        max_spread_pips=15.0,
        spread_pips=4.0,
        slippage_pips=1.0,
        min_lot=0.01,
        max_lot=0.01,
        max_open_positions_total=1,
        max_positions_per_symbol=1,
    )


async def run_backtest(days: int = 30, balance: float = 200.0, offset_days: int = 0):
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.backtest.metrics import compute_metrics, format_report

    cfg = make_config(days, balance, offset_days)
    eng = BacktestEngine(cfg, load_legacy_config(), quiet=True)
    label = f"{days}d off{offset_days}" if offset_days else f"{days}d"
    print(f"=== {label} | ${balance:.0f} | ADAPTIVE (tuned) ===", flush=True)
    try:
        result = await eng.run()
        print(f"DONE trades={len(result.trades)} balance={result.final_balance:.2f}", flush=True)
    except Exception as exc:
        print(f"BACKTEST FAILED: {exc}", flush=True)
        raise
    metrics = compute_metrics(result, cfg.timeframe)
    print("METRICS OK", flush=True)
    print(format_report(result, metrics, cfg.timeframe), flush=True)

    by_sub: dict[str, dict] = defaultdict(lambda: {"n": 0, "pnl": 0.0, "w": 0})
    for t in result.trades:
        meta = getattr(t, "metadata", None) or {}
        sub = str(meta.get("sub_strategy", "?"))
        by_sub[sub]["n"] += 1
        by_sub[sub]["pnl"] += t.pnl
        if t.pnl > 0:
            by_sub[sub]["w"] += 1
    print("By sub-strategy:", flush=True)
    for k, v in sorted(by_sub.items(), key=lambda x: -x[1]["n"]):
        wr = 100 * v["w"] / v["n"] if v["n"] else 0
        print(f"  {k}: trades={v['n']} pnl={v['pnl']:.2f} wr={wr:.1f}%", flush=True)
    return result, metrics


if __name__ == "__main__":
    import sys

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    asyncio.run(run_backtest(days=days, offset_days=offset))
