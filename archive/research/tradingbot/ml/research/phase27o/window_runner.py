"""Phase 27O — window loader with OOS strategy simulation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame
from tradingbot.ml.research.phase27n.hybrid_simulators import simulate_strategy
from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

WINDOWS = (30, 60, 90, 180, 365)

COMPARE_STRATEGIES = (
    "current_tp_sl",
    "time_exit",
    "partial_close_50",
    "structure_exit",
    "hybrid_a",
    "hybrid_d",
    "hybrid_b",
)


def load_candle_window(base_dir: Path, days: int) -> pd.DataFrame:
    raw = CandleStore(base_dir).load("XAUUSD", "M5")
    if raw is None or raw.empty:
        return pd.DataFrame()
    return normalize_candles_for_builder(prepare_calibration_candles(raw, days=days))


def load_window_cache(
    *,
    base_dir: Path,
    phase27m_cache: Path,
    days: int,
    phase27f_cache: Path | None = None,
) -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, Any]]:
    cache_records = phase27m_cache / f"window_{days}_records.json"
    cache_meta = phase27m_cache / f"window_{days}_meta.json"
    window = load_candle_window(base_dir, days)
    if window.empty:
        return [], window, {"error": "candles_unavailable", "days": days}

    if days == 30 and phase27f_cache and phase27f_cache.is_file():
        records = json.loads(phase27f_cache.read_text(encoding="utf-8"))
        meta_path = phase27f_cache.parent / "replay_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {"days": days}
        meta["source"] = "phase27f_cache"
        return records, window, meta

    if not cache_records.is_file():
        return [], window, {"error": "replay_cache_missing", "days": days}
    records = json.loads(cache_records.read_text(encoding="utf-8"))
    meta = json.loads(cache_meta.read_text(encoding="utf-8")) if cache_meta.is_file() else {"days": days}
    meta["source"] = "phase27m_cache"
    return records, window, meta


def simulate_trades(
    trades: list[dict[str, Any]],
    frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for trade in trades:
        results.append(
            {
                "timestamp": trade.get("timestamp"),
                "direction": trade.get("direction"),
                "baseline_pnl": float(trade["pnl"]),
                "strategies": {s: simulate_strategy(trade, frame, s) for s in COMPARE_STRATEGIES},
            }
        )
    return results


def process_window(
    *,
    base_dir: Path,
    phase27m_cache: Path,
    days: int,
    phase27f_cache: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame, dict[str, Any]]:
    records, window, meta = load_window_cache(
        base_dir=base_dir,
        phase27m_cache=phase27m_cache,
        days=days,
        phase27f_cache=phase27f_cache,
    )
    if not records or window.empty:
        return [], [], window, meta
    trades = build_completed_trades(records, window, symbol="XAUUSD")
    frame = prepare_indicator_frame(window)
    sim_results = simulate_trades(trades, frame)
    return trades, sim_results, frame, meta
