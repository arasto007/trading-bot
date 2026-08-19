#!/usr/bin/env python3
"""Run backtest and write JSON report (avoids stdout issues on Windows)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


async def run_once(
    *,
    days: int,
    offset: int,
    balance: float,
    label: str,
    confluence: bool,
    vol_only: bool = False,
) -> dict:
    os.environ["USE_ML_KERNEL"] = "false"
    os.environ["ADAPTIVE_REGIME_ENABLED"] = "false" if vol_only else "true"
    os.environ["VOL_REGIME_ENABLED"] = "true" if vol_only else "true"
    os.environ["ADAPTIVE_CONFLUENCE_ONLY"] = "true" if confluence else "false"

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
        enable_trailing=True,
        enable_emergency=True,
    )
    legacy = load_legacy_config()
    reg = build_strategy_registry(legacy)
    result = await BacktestEngine(cfg, legacy, quiet=True, strategies=reg).run()
    metrics = compute_metrics(result, cfg.timeframe)
    return {
        "label": label,
        "days": days,
        "offset_days": offset,
        "balance_start": balance,
        **metrics,
        "exit_reasons": metrics.get("exit_reasons", {}),
    }


async def main() -> int:
    balance = float(os.getenv("BT_BALANCE", "200"))
    reports = []
    for days, offset, label, conf, vol in (
        (14, 0, "recent_14d_confluence", True, False),
        (14, 14, "prev_14d_confluence", True, False),
        (14, 0, "recent_14d_vol_only", False, True),
    ):
        reports.append(await run_once(days=days, offset=offset, balance=balance, label=label, confluence=conf, vol_only=vol))

    # Approximate 28d combined (not compound — conservative sum of net)
    combined_net = sum(r["net_profit"] for r in reports[:2])
    combined_trades = sum(r["total_trades"] for r in reports[:2])
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "balance_start": balance,
        "approx_28d_net": round(combined_net, 2),
        "approx_28d_return_pct": round(combined_net / balance * 100, 2),
        "approx_28d_trades": combined_trades,
        "reports": reports,
    }
    out = ROOT / "data" / "backtest_adaptive_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
