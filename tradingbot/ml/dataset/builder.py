"""Event-based dataset builder — one row per trading decision point."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.roles import ENTRY_TIMEFRAME, role_for_timeframe
from tradingbot.ml.data.schema import MarketEventType
from tradingbot.ml.data.stores import CandleStore, EventStore
from tradingbot.ml.dataset.labels import label_from_future_candles
from tradingbot.ml.dataset.schema import (
    DATASET_SCHEMA_VERSION,
    DatasetBuildConfig,
    LabeledSample,
    SAMPLE_EVENT_TYPES,
)
from tradingbot.ml.dataset.splitter import assign_split_column
from tradingbot.ml.features.registry.registry import feature_names
from tradingbot.ml.features.reproducibility import hash_dataframe
from tradingbot.ml.features.store import FeatureStore

logger = logging.getLogger(__name__)

_EVENT_TYPES_FOR_SAMPLING = {
    MarketEventType.BOS.value,
    MarketEventType.CHOCH.value,
    MarketEventType.LIQUIDITY_SWEEP.value,
    MarketEventType.FVG.value,
    MarketEventType.ORDER_BLOCK.value,
    MarketEventType.TRADING_SESSION.value,
    "session_transition",
}


def _git_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


def _event_bar_index(event: dict[str, Any], candles: pd.DataFrame) -> int | None:
    meta = event.get("metadata") or {}
    if "bar_index" in meta:
        idx = int(meta["bar_index"])
        if 0 <= idx < len(candles):
            return idx
    ts = pd.Timestamp(event.get("ts_utc") or event.get("event_time"))
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    pos = candles.index.searchsorted(ts, side="right") - 1
    if pos < 0 or pos >= len(candles):
        return None
    return int(pos)


def detect_session_transitions(candles: pd.DataFrame, symbol: str) -> list[dict[str, Any]]:
    from tradingbot.ml.data.session_utils import session_record_at

    transitions: list[dict[str, Any]] = []
    prev_session: str | None = None
    for i, ts in enumerate(candles.index):
        if not isinstance(ts, datetime):
            ts = ts.to_pydatetime()  # type: ignore[union-attr]
        rec = session_record_at(ts, symbol)
        if prev_session is not None and rec.session != prev_session:
            transitions.append(
                {
                    "event_id": f"{symbol}|M5|session_transition|{ts.isoformat()}|{prev_session}->{rec.session}",
                    "event_type": "session_transition",
                    "symbol": symbol.upper(),
                    "timeframe": "M5",
                    "ts_utc": ts.isoformat(),
                    "event_time": ts.isoformat(),
                    "direction": 0,
                    "price": float(candles["close"].iloc[i]),
                    "metadata": {"bar_index": i, "from_session": prev_session, "to_session": rec.session},
                }
            )
        prev_session = rec.session
    return transitions


def _filter_sampling_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("event_type") in _EVENT_TYPES_FOR_SAMPLING]


def _merge_features_at(
    features: pd.DataFrame,
    ts: pd.Timestamp,
    feature_cols: list[str],
) -> dict[str, float]:
    if features is None or features.empty:
        return {c: 0.0 for c in feature_cols}
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    pos = features.index.searchsorted(ts, side="right") - 1
    if pos < 0:
        return {c: 0.0 for c in feature_cols}
    row = features.iloc[pos]
    return {c: float(row[c]) if c in row.index and pd.notna(row[c]) else 0.0 for c in feature_cols}


class DatasetBuilder:
    """
    Build supervised dataset from processed features + raw events + candles.

    Uses only data/ml/raw/ and data/ml/processed/features/ as inputs.
    """

    def __init__(
        self,
        config: DatasetBuildConfig | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        self.config = config or DatasetBuildConfig()
        self._base = base_dir
        self._candles = CandleStore(base_dir)
        self._events = EventStore(base_dir)
        self._features = FeatureStore(base_dir)

    def collect_events(self, symbol: str) -> list[dict[str, Any]]:
        sym = symbol.upper()
        anchor = self.config.timeframe.upper()
        events: list[dict[str, Any]] = []
        for tf in self.config.event_timeframes:
            events.extend(self._events.load_all(sym, tf))
        if self.config.include_session_transitions:
            candles = self._candles.load(sym, anchor)
            if candles is not None and not candles.empty:
                events.extend(detect_session_transitions(candles, sym))
        return _filter_sampling_events(events)

    def build(self, symbol: str | None = None) -> pd.DataFrame:
        sym = (symbol or self.config.symbol).upper()
        tf = self.config.timeframe.upper()

        candles = self._candles.load(sym, tf)
        features = self._features.load(sym, tf)
        if candles is None or candles.empty:
            logger.warning("No candles for dataset build: %s %s", sym, tf)
            return pd.DataFrame()
        if features is None or features.empty:
            logger.warning("No features for dataset build: %s %s", sym, tf)
            return pd.DataFrame()

        feature_cols = [c for c in feature_names() if c in features.columns]
        events = self.collect_events(sym)
        if not events:
            logger.warning("No sampling events for %s", sym)
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for event in events:
            eid = str(event.get("event_id", ""))
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)

            bar_idx = _event_bar_index(event, candles)
            if bar_idx is None:
                continue

            # Need future bars for labeling
            if bar_idx + 1 >= len(candles):
                continue

            ts = candles.index[bar_idx]
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            direction = int(event.get("direction") or 0)
            entry = float(event.get("price") or candles["close"].iloc[bar_idx])

            outcome = label_from_future_candles(
                candles,
                bar_idx,
                direction,
                future_window_bars=self.config.future_window_bars,
                atr_period=self.config.atr_period,
                tp_r=self.config.tp_r_multiple,
                sl_r=self.config.sl_r_multiple,
                entry_price=entry,
            )

            event_tf = str(event.get("timeframe", tf)).upper()
            role = role_for_timeframe(event_tf)
            role_str = role.value if role else "unknown"

            feat_row = _merge_features_at(features, pd.Timestamp(ts), feature_cols)

            sample = LabeledSample(
                timestamp=ts_iso,
                symbol=sym,
                timeframe=tf,
                event_type=str(event.get("event_type", "")),
                event_time=str(event.get("ts_utc") or ts_iso),
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
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = assign_split_column(
            df,
            purge_bars=self.config.purge_bars,
            timeframe=tf,
        )
        df["dataset_schema_version"] = DATASET_SCHEMA_VERSION
        return df

    def build_manifest(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        *,
        dataset_path: str | Path,
        hardening: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sym = symbol.upper()
        tf = timeframe.upper()
        candles = self._candles.load(sym, tf)
        features = self._features.load(sym, tf)
        events = self.collect_events(sym)

        def _hash_features(df: pd.DataFrame | None) -> str:
            if df is None or df.empty:
                return ""
            import hashlib

            payload = df.sort_index().to_csv().encode("utf-8")
            return hashlib.sha256(payload).hexdigest()

        from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint

        fingerprint = compute_dataset_fingerprint(df, self.config)
        manifest = {
            "symbol": sym,
            "timeframe": tf,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "build_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git_commit(),
            "sample_count": len(df),
            "source_candle_hash": hash_dataframe(candles) if candles is not None else "",
            "source_features_hash": _hash_features(features),
            "source_event_count": len(events),
            "future_window_bars": self.config.future_window_bars,
            "purge_bars": self.config.purge_bars,
            "dataset_storage_path": str(dataset_path),
            "dataset_hash": fingerprint.dataset_hash,
            "feature_hash": fingerprint.feature_hash,
            "label_config_hash": fingerprint.label_config_hash,
            "feature_version": fingerprint.feature_version,
            "label_config": fingerprint.label_config,
            "event_types": sorted(df["event_type"].unique().tolist()) if "event_type" in df.columns else [],
            "label_distribution": (
                {str(int(k)): int(v) for k, v in df["label"].value_counts().items()}
                if "label" in df.columns
                else {}
            ),
        }
        if hardening:
            manifest["hardening"] = hardening
        return manifest
