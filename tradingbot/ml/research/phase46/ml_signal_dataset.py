"""Phase 46 — ML signal-aligned training dataset (research only)."""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.phase22f.config import RapidDataset, configure_research_env
from tradingbot.ml.research.phase49.bar_index import resolve_bar_index
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

TEHRAN = ZoneInfo("Asia/Tehran")
ROOT = Path(__file__).resolve().parents[4]
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"


def build_historical_dataset(trading_days: int, *, end: datetime | None = None) -> RapidDataset:
    """Historical window for ML signal capture (research only)."""
    end = (end or datetime(2025, 12, 31, 23, 59, tzinfo=TEHRAN)).astimezone(TEHRAN)
    start_date = end.date()
    counted = 0
    while counted < trading_days:
        if start_date.weekday() < 5:
            counted += 1
        if counted < trading_days:
            start_date -= timedelta(days=1)
    start = datetime.combine(start_date, time(0, 0), tzinfo=TEHRAN)
    end_dt = datetime.combine(end.date(), time(23, 59), tzinfo=TEHRAN)
    return RapidDataset(label="H", trading_days=trading_days, start=start, end=end_dt)


def _cache_path(label: str) -> Path:
    return CACHE_DIR / f"ml_signals_fullest_{label}.json"


def load_cached_signals(label: str) -> dict | None:
    p = _cache_path(label)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_cached_signals(label: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(label).write_text(json.dumps(payload, default=str), encoding="utf-8")


async def collect_ml_signals_multi(
    labels: tuple[str, ...] = ("A", "B", "C", "H"),
    *,
    use_cache: bool = True,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Collect raw ML signals across datasets using fullest candle history."""
    from tradingbot.ml.research.phase22f.config import build_dataset
    from tradingbot.ml.research.phase34a.collector import collect_raw_ml_signals

    configure_research_env()
    out: list[dict[str, Any]] = []
    for label in labels:
        if label == "H":
            ds = build_historical_dataset(45)
        else:
            ds = build_dataset(label)

        cached = None if force else (load_cached_signals(label) if use_cache else None)
        if cached is None:
            print(f"  collecting ML signals dataset={label} fullest_candles...", flush=True)
            cached = await collect_raw_ml_signals(ds, use_fullest_candles=True)
            save_cached_signals(label, cached)
        for sig in cached.get("signals", []):
            rec = dict(sig)
            rec["source_dataset"] = label
            out.append(rec)
    return out


def build_ml_signal_dataset(
    signals: list[dict[str, Any]],
    *,
    future_window: int = 72,
) -> pd.DataFrame:
    """Build labeled feature rows at ML signal bars (production SL/TP labels)."""
    if not signals:
        return pd.DataFrame()

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

    builder = FeatureBuilder("XAUUSD", base_dir=None)
    rows: list[dict[str, Any]] = []

    for sig in signals:
        direction_str = str(sig.get("direction", ""))
        if direction_str not in ("BUY", "SELL"):
            continue
        ts = pd.to_datetime(sig["timestamp"], utc=True)
        idx = resolve_bar_index(candles, ts)
        if idx < 60 or idx >= len(candles) - future_window - 1:
            continue
        if candles.index[idx] != ts:
            continue
        direction = 1 if direction_str == "BUY" else -1
        entry = float(candles["close"].iloc[idx])
        sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction)
        if sl <= 0 or tp <= 0:
            continue
        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl, tp,
            future_window_bars=future_window,
            entry_price=entry,
        )
        label = int(resolved["label"])
        if label == int(Label.NO_RESOLUTION):
            continue

        feats = builder.compute_at(candles, idx, h4_df=h4, m15_df=m15)
        row = {
            "timestamp": pd.to_datetime(sig["timestamp"], utc=True),
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
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    df["dataset_version"] = "v6_ml_signals"
    return df
