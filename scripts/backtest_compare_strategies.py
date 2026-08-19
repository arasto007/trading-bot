#!/usr/bin/env python3
"""Compare strategy variants on 14d real MT5 data."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


async def _run(label: str, env: dict, days: int = 14, offset: int = 0):
    for k, v in env.items():
        os.environ[k] = v
    # force re-import of config-dependent modules
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine
    from tradingbot.backtest.metrics import compute_metrics
    from tradingbot.ml.integration.factory import build_strategy_registry

    cfg = BacktestConfig(
        symbols=["XAUUSD"],
        timeframe="M5",
        days=days,
        start_offset_days=offset,
        warmup=500,
        initial_balance=200,
        risk_per_trade=0.01,
        max_trades_per_day=3,
        cooldown_bars=12,
        require_htf_alignment_m5=False,
        use_meta_labeler=False,
        max_spread_pips=15,
        spread_pips=4,
        slippage_pips=1,
        min_lot=0.01,
        max_lot=0.01,
        enable_trailing=False,
        enable_emergency=False,
        use_cache=True,
    )
    legacy = load_legacy_config()
    reg = build_strategy_registry(legacy)
    eng = BacktestEngine(cfg, legacy, quiet=True, strategies=reg)
    result = await eng.run()
    m = compute_metrics(result, "M5")
    print(
        f"{label:20s} trades={m['total_trades']:3d}  "
        f"net={m['net_profit']:7.2f}  ret={m['return_pct']:6.1f}%  "
        f"PF={m['profit_factor']}  WR={m['win_rate_pct']:.0f}%  "
        f"DD={m['max_drawdown_pct']:.1f}%",
        flush=True,
    )
    return m


async def main():
    print("=== Strategy comparison | 14d | $200 | real MT5 ===", flush=True)
    await _run("VOL_ONLY", {"USE_ML_KERNEL": "false", "ADAPTIVE_REGIME_ENABLED": "false", "VOL_REGIME_ENABLED": "true"})
    await _run("ADAPTIVE_OLD", {"USE_ML_KERNEL": "false", "ADAPTIVE_REGIME_ENABLED": "true"})
    # confluence-only variant via env flag
    os.environ["ADAPTIVE_CONFLUENCE_ONLY"] = "true"
    await _run("CONFLUENCE", {"USE_ML_KERNEL": "false", "ADAPTIVE_REGIME_ENABLED": "true"})


if __name__ == "__main__":
    asyncio.run(main())
