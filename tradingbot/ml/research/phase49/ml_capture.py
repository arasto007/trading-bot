"""Phase 49 — expanded ML capture with fixed bar indexing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.phase22f.config import RapidDataset, configure_research_env
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast
from tradingbot.ml.research.phase46.ml_signal_dataset import (
    build_historical_dataset,
    load_cached_signals,
    save_cached_signals,
)
from tradingbot.ml.research.phase49.bar_index import resolve_bar_index
from tradingbot.ml.research.phase49.historical_windows import build_quarter_dataset, quarter_labels

ROOT = Path(__file__).resolve().parents[4]
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase49" / ".cache"
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts"
PARTIAL_V7 = ARTIFACTS / "dataset_v7_partial.parquet"


def _dedupe_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for sig in sorted(signals, key=lambda s: str(s.get("timestamp", ""))):
        direction = str(sig.get("direction", ""))
        if direction not in ("BUY", "SELL"):
            continue
        key = (str(sig.get("timestamp")), direction)
        if key in seen:
            continue
        seen.add(key)
        out.append(sig)
    return out


async def _dataset_for_label(label: str) -> "RapidDataset":
    from tradingbot.ml.research.phase22f.config import build_dataset

    if label.startswith("Y"):
        year = int(label[1:5])
        quarter = int(label[6])
        return build_quarter_dataset(year, quarter)
    if label == "H":
        return build_historical_dataset(45)
    return build_dataset(label)


async def _collect_label_async(
    label: str,
    *,
    force: bool = False,
    use_cache: bool = True,
) -> tuple[str, dict[str, Any]]:
    from tradingbot.ml.research.phase34a.collector import collect_raw_ml_signals

    if not force and use_cache:
        cached = load_cached_signals(label)
        if cached is not None:
            return label, cached

    print(f"  collecting ML signals label={label}...", flush=True)
    ds = await _dataset_for_label(label)
    cached = await collect_raw_ml_signals(ds, use_fullest_candles=True)
    save_cached_signals(label, cached)
    return label, cached


def _process_collect_label(args: tuple[str, bool, bool]) -> tuple[str, dict[str, Any]]:
    """Process-pool worker (Windows spawn-safe)."""
    label, force, use_cache = args
    import asyncio

    return asyncio.run(_collect_label_async(label, force=force, use_cache=use_cache))


async def collect_all_signals(
    *,
    use_cache: bool = True,
    force: bool = False,
    include_legacy: bool = True,
    year_start: int = 2021,
    year_end: int = 2026,
) -> list[dict[str, Any]]:
    configure_research_env()
    out: list[dict[str, Any]] = []
    labels: list[str] = list(quarter_labels(year_start, year_end))
    if include_legacy:
        labels = ["A", "B", "C", "H"] + labels

    parallel = max(1, int(os.environ.get("PHASE49_PARALLEL_QUARTERS", "1") or "1"))
    parallel = min(parallel, max(1, (os.cpu_count() or 4) - 1), 4)

    pending: list[str] = []
    for label in labels:
        cached = None if force else (load_cached_signals(label) if use_cache else None)
        if cached is not None:
            for sig in cached.get("signals", []):
                rec = dict(sig)
                rec["source_dataset"] = label
                out.append(rec)
        else:
            pending.append(label)

    if not pending:
        return _dedupe_signals(out)

    if parallel > 1 and len(pending) > 1:
        print(f"  parallel quarter capture: workers={parallel} pending={len(pending)}", flush=True)
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(_process_collect_label, (label, force, use_cache)): label
                for label in pending
            }
            for fut in as_completed(futures):
                label, cached = fut.result()
                for sig in cached.get("signals", []):
                    rec = dict(sig)
                    rec["source_dataset"] = label
                    out.append(rec)
    else:
        for label in pending:
            _, cached = await _collect_label_async(label, force=force, use_cache=use_cache)
            for sig in cached.get("signals", []):
                rec = dict(sig)
                rec["source_dataset"] = label
                out.append(rec)

    return _dedupe_signals(out)


def _build_one_row(
    sig: dict[str, Any],
    candles: pd.DataFrame,
    m15: pd.DataFrame | None,
    h4: pd.DataFrame | None,
    *,
    future_window: int,
) -> dict[str, Any] | None:
    from tradingbot.ml.features.builder import FeatureBuilder

    direction_str = str(sig.get("direction", ""))
    if direction_str not in ("BUY", "SELL"):
        return None
    direction = 1 if direction_str == "BUY" else -1
    ts = pd.to_datetime(sig["timestamp"], utc=True)
    idx = resolve_bar_index(candles, ts)
    if idx < 60 or idx >= len(candles) - future_window - 1:
        return None
    if candles.index[idx] != ts:
        return None
    entry = float(candles["close"].iloc[idx])
    sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction)
    if sl <= 0 or tp <= 0:
        return None
    resolved = resolve_label_with_sl_tp(
        candles, idx, direction, sl, tp,
        future_window_bars=future_window,
        entry_price=entry,
    )
    label = int(resolved["label"])
    if label == int(Label.NO_RESOLUTION):
        return None
    builder = FeatureBuilder("XAUUSD", base_dir=None)
    feats = builder.compute_at(candles, idx, h4_df=h4, m15_df=m15)
    return {
        "timestamp": ts,
        "bar_index": idx,
        "event_type": "ml_raw_signal",
        "direction": direction,
        "entry_price": entry,
        "label_v3": label,
        "label": label,
        "stop_loss_v3": round(sl, 6),
        "take_profit_v3": round(tp, 6),
        "ml_probability": float(sig.get("probability", 0)),
        "ml_confidence": float(sig.get("confidence", 0)),
        "regime": str(sig.get("regime", "")),
        "source_dataset": str(sig.get("source_dataset", "")),
        "engine": str(sig.get("engine", "")),
        **feats,
    }


def build_ml_signal_dataset_v7(
    signals: list[dict[str, Any]],
    *,
    future_window: int = 72,
    resume: bool = True,
) -> pd.DataFrame:
    """Build v7 with timestamp-resolved absolute bar indices (fixes slice-relative bug)."""
    if not signals:
        return pd.DataFrame()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    done_keys: set[tuple[str, int]] = set()
    existing_rows: list[dict[str, Any]] = []
    if resume and PARTIAL_V7.is_file():
        partial = pd.read_parquet(PARTIAL_V7)
        if not partial.empty:
            existing_rows = partial.to_dict("records")
            for row in existing_rows:
                done_keys.add((str(row["timestamp"]), int(row["direction"])))
            print(f"  resume: loaded {len(existing_rows)} partial rows", flush=True)

    candles = resolve_fullest_candles("XAUUSD", "M5")
    if candles is None or candles.empty:
        return pd.DataFrame()

    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.features.builder import FeatureBuilder

    cs = CandleStore(None)

    def _norm(frame: pd.DataFrame | None) -> pd.DataFrame | None:
        if frame is None or frame.empty:
            return None
        out = frame
        if not isinstance(out.index, pd.DatetimeIndex):
            if "timestamp" in out.columns:
                out = out.set_index("timestamp")
            elif "time" in out.columns:
                out = out.set_index("time")
        out = out.copy()
        out.index = pd.to_datetime(out.index, utc=True)
        return out.sort_index()

    m15 = _norm(cs.load("XAUUSD", "M15"))
    h4 = _norm(cs.load("XAUUSD", "H4"))
    rows: list[dict[str, Any]] = list(existing_rows)

    pending = []
    for sig in signals:
        direction_str = str(sig.get("direction", ""))
        if direction_str not in ("BUY", "SELL"):
            continue
        direction = 1 if direction_str == "BUY" else -1
        ts = pd.to_datetime(sig["timestamp"], utc=True)
        if (str(ts), direction) in done_keys:
            continue
        pending.append(sig)

    workers = min(
        int(os.environ.get("PHASE49_BUILD_WORKERS", "0") or 0) or min(8, max(2, (os.cpu_count() or 4) - 1)),
        8,
    )
    built = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_build_one_row, sig, candles, m15, h4, future_window=future_window): sig
            for sig in pending
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row is None:
                continue
            rows.append(row)
            done_keys.add((str(row["timestamp"]), int(row["direction"])))
            built += 1
            if built % 50 == 0:
                pd.DataFrame(rows).to_parquet(PARTIAL_V7, index=False)
                print(f"    checkpoint: {len(rows)} rows ({built} new)", flush=True)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    df["dataset_version"] = "v7_ml_signals_fixed"
    df.to_parquet(PARTIAL_V7, index=False)
    return df
