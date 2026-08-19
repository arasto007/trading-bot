"""Phase 19C — rollback validation (filters OFF == Phase 19A)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.phase19a.backtest import run_production_backtest
from tradingbot.ml.phase19a.metrics import compute_performance
from tradingbot.ml.phase19c.backtest import run_filtered_backtest
from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings


def _trade_key(rec: dict[str, Any]) -> tuple:
    return (
        rec.get("timestamp"),
        rec.get("direction"),
        rec.get("regime"),
        rec.get("engine"),
    )


def _accepted_trades(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r.get("allowed")]


def validate_rollback(
    candles: pd.DataFrame,
    dataset: pd.DataFrame,
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 1095,
    stride: int = 5,
) -> dict[str, Any]:
    """
    Verify disabling all filters reproduces Phase 19A backtest results.
    """
    disabled = ProfitabilityFilterSettings(
        enable_rsi=False,
        enable_adx=False,
    )

    baseline = run_production_backtest(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        stride=stride,
    )
    filtered_off = run_filtered_backtest(
        candles,
        dataset,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        stride=stride,
        filter_settings=disabled,
    )

    base_trades = _accepted_trades(baseline["records"])
    off_trades = _accepted_trades(filtered_off["records"])
    base_perf = compute_performance(baseline["records"])
    off_perf = compute_performance(filtered_off["records"])

    base_keys = {_trade_key(t) for t in base_trades}
    off_keys = {_trade_key(t) for t in off_trades}
    keys_match = base_keys == off_keys

    metrics_match = (
        base_perf["trades"] == off_perf["trades"]
        and abs(base_perf["profit_factor"] - off_perf["profit_factor"]) < 1e-4
        and abs(base_perf["expectancy_r"] - off_perf["expectancy_r"]) < 1e-4
        and abs(base_perf["net_profit_r"] - off_perf["net_profit_r"]) < 1e-4
        and base_perf["maximum_drawdown_r"] == off_perf["maximum_drawdown_r"]
    )

    passed = keys_match and metrics_match and filtered_off["filter_blocks"] == 0

    return {
        "phase": "19C",
        "passed": passed,
        "days": days,
        "baseline_trades": len(base_trades),
        "filters_off_trades": len(off_trades),
        "trade_keys_match": keys_match,
        "metrics_match": metrics_match,
        "filter_blocks_with_disabled": filtered_off["filter_blocks"],
        "baseline_performance": base_perf,
        "filters_off_performance": off_perf,
        "equivalence": "PASS" if passed else "FAIL",
    }
