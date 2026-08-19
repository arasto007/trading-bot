"""Phase 13.3 — walk-forward trend backtest validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.regime_detector.regime_validator import build_expanding_windows
from tradingbot.ml.research.trend_strategy.trend_backtest import run_trend_backtest


def _year_mask(ts: pd.Series, start: int, end: int):
    years = pd.to_datetime(ts, utc=True).dt.year
    return (years >= start) & (years <= end)


def _split_window(frame: pd.DataFrame, window: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "train_end" in window:
        ordered = frame.sort_values("timestamp").reset_index(drop=True)
        return ordered.iloc[: window["train_end"]], ordered.iloc[window["train_end"] :]

    ts = frame["timestamp"]
    tr_s, tr_e = window["train_years"]
    te_s, te_e = window["test_years"]
    train = frame.loc[_year_mask(ts, tr_s, tr_e)]
    test = frame.loc[_year_mask(ts, te_s, te_e)]
    return train, test


def run_walk_forward(
    frame: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    seed: int = 42,
) -> dict[str, Any]:
    """Expanding windows 2021-2026; backtest on test slice only (no shuffle)."""
    _ = seed
    windows_out: list[dict[str, Any]] = []
    dummy_ts = pd.DataFrame({"timestamp": frame["timestamp"]})
    for window in build_expanding_windows(dummy_ts):
        _train, test = _split_window(frame, window)
        if len(test) < 50:
            windows_out.append({"window_id": window["window_id"], "skipped": True})
            continue
        bt = run_trend_backtest(test, symbol=symbol)
        windows_out.append(
            {
                "window_id": window["window_id"],
                "test_rows": len(test),
                "test_period": window.get("test_years"),
                "metrics": bt["metrics"],
                "trades": bt["metrics"]["trades"],
                "trend_only": bt["trend_only"],
                "shuffle": False,
            }
        )

    return {
        "phase": "13.3",
        "windows": windows_out,
        "chronological": True,
        "expanding": True,
    }
