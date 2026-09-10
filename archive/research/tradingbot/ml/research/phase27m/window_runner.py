"""Phase 27M — multi-window replay and exit simulation runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27l.exit_simulators import simulate_exit
from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

STRATEGIES = (
    "current_tp_sl",
    "time_exit",
    "dynamic_tp_1.5r",
    "structure_exit",
    "atr_exit",
    "partial_close_50",
)

WARMUP_BARS = 300


def load_candle_window(base_dir: Path, days: int) -> pd.DataFrame:
    raw = CandleStore(base_dir).load("XAUUSD", "M5")
    if raw is None or raw.empty:
        return pd.DataFrame()
    return normalize_candles_for_builder(prepare_calibration_candles(raw, days=days))


def load_or_replay_window(
    *,
    base_dir: Path,
    cache_dir: Path,
    days: int,
    external_cache: Path | None = None,
) -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_records = cache_dir / f"window_{days}_records.json"
    cache_meta = cache_dir / f"window_{days}_meta.json"

    window = load_candle_window(base_dir, days)
    if window.empty:
        return [], window, {"error": "candles_unavailable", "days": days}

    if external_cache and external_cache.is_file() and days == 30:
        records = json.loads(external_cache.read_text(encoding="utf-8"))
        meta = json.loads((external_cache.parent / "replay_meta.json").read_text(encoding="utf-8"))
        meta["source"] = "phase27f_cache"
        return records, window, meta

    if cache_records.is_file() and cache_meta.is_file():
        records = json.loads(cache_records.read_text(encoding="utf-8"))
        meta = json.loads(cache_meta.read_text(encoding="utf-8"))
        return records, window, meta

    records, meta = run_unified_pipeline_replay(
        base_dir=str(base_dir),
        symbol="XAUUSD",
        timeframe="M5",
        days=days,
        tail_only=None,
        stride=1,
        warmup_bars=WARMUP_BARS,
        use_forming_bar_adapter=True,
    )
    meta["replay_days"] = days
    cache_records.write_text(json.dumps(records), encoding="utf-8")
    cache_meta.write_text(json.dumps(meta), encoding="utf-8")
    return records, window, meta


def simulate_window_trades(
    trades: list[dict[str, Any]],
    frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for trade in trades:
        row = {
            "timestamp": trade.get("timestamp"),
            "direction": trade.get("direction"),
            "baseline_pnl": float(trade["pnl"]),
            "strategies": {s: simulate_exit(trade, frame, s) for s in STRATEGIES},
        }
        results.append(row)
    return results
