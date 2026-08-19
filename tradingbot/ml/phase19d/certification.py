"""Phase 19D — complete production path backtest certification."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19c.backtest import run_filtered_backtest
from tradingbot.ml.phase19c.filters import load_filter_settings
from tradingbot.ml.phase19d.config import BACKTEST_WINDOWS_DAYS


def run_certification_backtests(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    stride: int = 5,
) -> dict[str, Any]:
    """Chronological replay on full production path (v41 + phase9_9 + Phase 19C filters)."""
    settings = load_filter_settings()
    windows: dict[str, Any] = {}
    all_records: list[dict[str, Any]] = []

    for days in BACKTEST_WINDOWS_DAYS:
        label = f"{days}d"
        bt = run_filtered_backtest(
            candles,
            dataset,
            base_dir=base_dir,
            symbol=symbol,
            timeframe=timeframe,
            days=days,
            stride=stride,
            filter_settings=settings,
        )
        perf = compute_performance(bt["records"])
        windows[label] = {
            "days": days,
            "bars_evaluated": bt["bars_evaluated"],
            "filter_blocks": bt["filter_blocks"],
            "performance": perf,
        }
        if days == BACKTEST_WINDOWS_DAYS[-1]:
            all_records = bt["records"]

    perf_3y = windows.get("1095d", {}).get("performance", {})
    gates = {
        "profit_factor_ge_1_30": float(perf_3y.get("profit_factor", 0)) >= 1.30,
        "expectancy_ge_0_15": float(perf_3y.get("expectancy_r", 0)) >= 0.15,
        "max_drawdown_le_20r": abs(float(perf_3y.get("maximum_drawdown_r", 0))) <= 20.0,
        "positive_net_profit": float(perf_3y.get("net_profit_r", 0)) > 0,
        "min_trades": int(perf_3y.get("trades", 0)) >= 15,
    }

    return {
        "phase": "19D",
        "read_only": True,
        "system_under_test": {
            "trend": "trend_rf_v41",
            "range": "phase9_9",
            "filters": ["rsi_mid", "adx_15_50"],
            "filter_settings": settings.to_dict(),
        },
        "windows": windows,
        "gates": gates,
        "passed": all(gates.values()),
        "records_3y": all_records,
    }
