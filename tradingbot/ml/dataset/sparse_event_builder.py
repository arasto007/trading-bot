"""Event-sparse dataset build — compute features only at sampling events (Phase 9.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.position_logic import pip_size
from tradingbot.ml.data.historical_quality_validator import normalize_candles, production_date_range
from tradingbot.ml.data.market_event_extractor import extract_market_events
from tradingbot.ml.data.roles import CONTEXT_TIMEFRAME, ENTRY_TIMEFRAME, HIGHER_TIMEFRAME_BIAS, role_for_timeframe
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.builder import (
    _event_bar_index,
    _filter_sampling_events,
    detect_session_transitions,
)
from tradingbot.ml.dataset.hardening import run_dataset_hardening
from tradingbot.ml.dataset.labels import label_from_future_candles
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig, LabeledSample
from tradingbot.ml.dataset.splitter import assign_split_column
from tradingbot.ml.features.builder import FeatureBuilder
from tradingbot.ml.features.registry.registry import feature_names

logger = logging.getLogger(__name__)


def build_bar_spread_proxy_series(m5_df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.Series:
    """OHLC-derived spread proxy when tick/spread store is unavailable (historical builds)."""
    if m5_df is None or m5_df.empty:
        return pd.Series(dtype=float)
    pip = pip_size(symbol.upper())
    if pip <= 0:
        pip = 0.01
    spread = ((m5_df["high"] - m5_df["low"]) / pip).clip(0.05, 5.0)
    return pd.Series(spread.values, index=m5_df.index)


def patch_spread_features(df: pd.DataFrame, m5_df: pd.DataFrame, symbol: str = "XAUUSD") -> pd.DataFrame:
    """Backfill spread_pips / spread_zscore / spread_spike from M5 bar-range proxy."""
    if df is None or df.empty or m5_df is None or m5_df.empty:
        return df
    spread_series = build_bar_spread_proxy_series(m5_df, symbol)
    if spread_series.empty:
        return df

    out = df.copy()
    rolling = spread_series.rolling(60, min_periods=5)
    mean = rolling.mean()
    std = rolling.std().replace(0, np.nan)
    z = ((spread_series - mean) / std).fillna(0.0)
    spike = (z > 2.0).astype(float)

    spread_frame = pd.DataFrame(
        {
            "spread_pips": spread_series,
            "spread_zscore": z,
            "spread_spike": spike,
        },
        index=spread_series.index,
    )
    spread_frame.index.name = "time"

    out["_ts"] = pd.to_datetime(out["timestamp"], utc=True)
    spread_frame = spread_frame.reset_index()
    spread_frame.rename(columns={"time": "_ts"}, inplace=True)
    merged = out.merge(spread_frame, on="_ts", how="left", suffixes=("", "_proxy"))
    for col in ("spread_pips", "spread_zscore", "spread_spike"):
        proxy_col = f"{col}_proxy" if f"{col}_proxy" in merged.columns else col
        if proxy_col in merged.columns:
            merged[col] = merged[proxy_col].fillna(merged.get(col, 0.0))
            if proxy_col != col:
                merged.drop(columns=[proxy_col], inplace=True)
    return merged.drop(columns=["_ts"])


def _event_to_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "to_dict"):
        payload = event.to_dict()
        payload.setdefault("event_time", payload.get("ts_utc"))
        if "metadata" in payload and isinstance(payload["metadata"], dict):
            meta = payload["metadata"]
            if "bar_index" in meta:
                payload.setdefault("bar_index", meta["bar_index"])
        return payload
    raise TypeError(f"unsupported event type: {type(event)}")


def filter_candles_to_production_window(
    df: pd.DataFrame,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    norm = normalize_candles(df)
    if norm is None or norm.empty:
        return pd.DataFrame()
    if start is None or end is None:
        start, end = production_date_range()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")
    mask = (norm.index >= start_ts) & (norm.index <= end_ts)
    return norm.loc[mask].copy()


def collect_production_events(
    symbol: str,
    candles_by_tf: dict[str, pd.DataFrame],
    *,
    config: DatasetBuildConfig,
) -> list[dict[str, Any]]:
    sym = symbol.upper()
    anchor = config.timeframe.upper()
    events: list[dict[str, Any]] = []

    for tf in config.event_timeframes:
        tf_u = tf.upper()
        candles = candles_by_tf.get(tf_u)
        if candles is None or candles.empty:
            continue
        cfg = get_price_action_config(sym, tf_u)
        for raw in extract_market_events(candles, sym, tf_u, cfg=cfg):
            events.append(_event_to_dict(raw))

    if config.include_session_transitions:
        anchor_candles = candles_by_tf.get(anchor)
        if anchor_candles is not None and not anchor_candles.empty:
            events.extend(detect_session_transitions(anchor_candles, sym))

    return _filter_sampling_events(events)


@dataclass
class SparseBuildResult:
    symbol: str
    timeframe: str
    status: str
    row_count: int = 0
    event_count: int = 0
    window_start_utc: str | None = None
    window_end_utc: str | None = None
    m5_bars_in_window: int = 0
    hardening: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "passed": self.passed,
            "row_count": self.row_count,
            "event_count": self.event_count,
            "window_start_utc": self.window_start_utc,
            "window_end_utc": self.window_end_utc,
            "m5_bars_in_window": self.m5_bars_in_window,
            "hardening": self.hardening,
            "errors": self.errors,
            "build_mode": "event_sparse_5y",
        }


class SparseEventDatasetBuilder:
    """
    Build labeled dataset by computing causal features only at event bar indices.

    Uses production 5Y candle window on M5/M15 while retaining full H4/M15 history
    for HTF alignment. Avoids materializing features for every M5 bar.
    """

    def __init__(
        self,
        config: DatasetBuildConfig | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.config = config or DatasetBuildConfig()
        self.base_dir = base_dir
        self._candles = CandleStore(base_dir)

    def build(self, symbol: str | None = None) -> tuple[pd.DataFrame, SparseBuildResult]:
        sym = (symbol or self.config.symbol).upper()
        tf = self.config.timeframe.upper()
        result = SparseBuildResult(symbol=sym, timeframe=tf, status="fail")

        start, end = production_date_range()
        m5_full = normalize_candles(self._candles.load(sym, tf))
        h4_full = normalize_candles(self._candles.load(sym, HIGHER_TIMEFRAME_BIAS))
        m15_full = normalize_candles(self._candles.load(sym, CONTEXT_TIMEFRAME))

        if m5_full is None or m5_full.empty:
            result.errors.append("no_m5_candles")
            return pd.DataFrame(), result

        m5_window = filter_candles_to_production_window(m5_full, start=start, end=end)
        if m5_window.empty:
            result.errors.append("empty_5y_window")
            return pd.DataFrame(), result

        m15_window = filter_candles_to_production_window(m15_full, start=start, end=end) if m15_full is not None else None

        result.window_start_utc = m5_window.index.min().isoformat()
        result.window_end_utc = m5_window.index.max().isoformat()
        result.m5_bars_in_window = len(m5_window)

        candles_by_tf = {tf: m5_window}
        if m15_window is not None and not m15_window.empty:
            candles_by_tf[CONTEXT_TIMEFRAME] = m15_window

        events = collect_production_events(sym, candles_by_tf, config=self.config)
        result.event_count = len(events)
        if not events:
            result.errors.append("no_events_in_5y_window")
            return pd.DataFrame(), result

        feature_builder = FeatureBuilder(sym, base_dir=str(self.base_dir) if self.base_dir else None)
        spread_proxy = build_bar_spread_proxy_series(m5_window, sym)

        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        total = len(events)

        for n, event in enumerate(events, start=1):
            if n % 250 == 0:
                logger.info("Sparse feature build progress: %d / %d events", n, total)

            eid = str(event.get("event_id", ""))
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)

            bar_idx = _event_bar_index(event, m5_window)
            if bar_idx is None:
                continue
            if bar_idx + 1 >= len(m5_window):
                continue

            ts = m5_window.index[bar_idx]
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            direction = int(event.get("direction") or 0)
            entry = float(event.get("price") or m5_window["close"].iloc[bar_idx])

            outcome = label_from_future_candles(
                m5_window,
                bar_idx,
                direction,
                future_window_bars=self.config.future_window_bars,
                atr_period=self.config.atr_period,
                tp_r=self.config.tp_r_multiple,
                sl_r=self.config.sl_r_multiple,
                entry_price=entry,
            )

            feat_row = feature_builder.compute_at(
                m5_window,
                bar_idx,
                h4_df=h4_full,
                m15_df=m15_full,
                spread_series=spread_proxy,
            )

            missing_feats = [name for name in feature_names() if name not in feat_row]
            if missing_feats:
                for name in missing_feats:
                    feat_row[name] = 0.0

            event_tf = str(event.get("timeframe", tf)).upper()
            role = role_for_timeframe(event_tf)
            role_str = role.value if role else "unknown"

            sample = LabeledSample(
                timestamp=ts_iso,
                symbol=sym,
                timeframe=tf,
                event_type=str(event.get("event_type", "")),
                event_time=str(event.get("ts_utc") or event.get("event_time") or ts_iso),
                event_id=eid or f"{sym}|{tf}|{event.get('event_type')}|{ts_iso}",
                timeframe_role=role_str,
                entry_price=outcome.entry_price,
                direction=outcome.direction,
                stop_loss=outcome.stop_loss,
                take_profit=outcome.take_profit,
                label=outcome.label,
                future_window_bars=outcome.future_window_bars,
                tp_hit=outcome.tp_hit,
                sl_hit=outcome.sl_hit,
                mfe=outcome.mfe,
                mae=outcome.mae,
                future_return=outcome.future_return,
                risk_unit=outcome.risk_unit,
                features=feat_row,
            )
            rows.append(sample.to_row())

        if not rows:
            result.errors.append("no_labeled_rows")
            return pd.DataFrame(), result

        df = pd.DataFrame(rows)
        df = assign_split_column(
            df,
            purge_bars=self.config.purge_bars,
            timeframe=tf,
        )
        df["dataset_schema_version"] = DATASET_SCHEMA_VERSION

        try:
            result.hardening = run_dataset_hardening(
                df,
                sym,
                tf,
                self.config,
                base_dir=self.base_dir,
            )
        except Exception as exc:
            logger.warning("Hardening failed: %s", exc)
            result.errors.append(f"hardening:{exc}")

        result.row_count = len(df)
        result.status = "pass"
        return df, result

    def build_and_store(self, symbol: str, timeframe: str) -> tuple[pd.DataFrame, SparseBuildResult, Path | None]:
        from tradingbot.ml.dataset.store import DatasetStore

        df, result = self.build(symbol)
        if df.empty or not result.passed:
            return df, result, None
        path = DatasetStore(self.base_dir).store(symbol, timeframe, df)
        return df, result, path
