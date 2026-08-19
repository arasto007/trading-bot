"""Phase 15B — singleton caches for ML kernel pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.data.paths import normalize_ml_base_dir, phase9_9_model_path
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle
from tradingbot.ml.phase15a.engine_registry import EngineRegistry
from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, load_trend_bundle
from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id, resolve_bundle_version
from tradingbot.ml.phase15a.config import TREND_ENGINE_V41_ID
from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

TOP5_FEATURE_COLUMNS = frozenset({
    "adx_acceleration",
    "swing_efficiency",
    "fractal_dimension_proxy",
    "trend_age",
    "ema_curvature",
})

FEATURE_CACHE_MAX_SLOTS = 64
TOP5_CACHE_MAX_SLOTS = 64
MARKET_CONTEXT_CACHE_MAX_SLOTS = 256


def resolve_closed_candle_timestamp(candles: pd.DataFrame) -> str:
    """ISO UTC timestamp for the last closed candle — never a positional index."""
    from tradingbot.domain.ohlcv import exclude_forming_bar

    closed = exclude_forming_bar(candles)
    if closed is not None and not closed.empty:
        ts = pd.Timestamp(closed.index[-1])
    elif candles is not None and not candles.empty:
        ts = pd.Timestamp(candles.index[-1])
    else:
        raise ValueError("candles_empty")
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def unified_row_fingerprint(row: pd.Series) -> str:
    """Stable fingerprint of the unified feature row used for prediction."""
    payload: dict[str, Any] = {}
    for key, value in row.items():
        name = str(key)
        if pd.isna(value):
            payload[name] = None
        elif isinstance(value, (bool, np.bool_)):
            payload[name] = bool(value)
        elif isinstance(value, (int, float, np.integer, np.floating)):
            payload[name] = round(float(value), 8)
        elif isinstance(value, str):
            payload[name] = value
        else:
            payload[name] = str(value)
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def unified_frame_sha256(df: pd.DataFrame) -> str:
    """Stable SHA256 over unified feature dataframe values (column-order sorted)."""
    if df is None or df.empty:
        return hashlib.sha256(b"empty").hexdigest()
    ordered = df.sort_index(axis=1)
    parts: list[bytes] = []
    for col in ordered.columns:
        series = ordered[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            parts.append(pd.to_datetime(series, utc=True).astype("int64").to_numpy().tobytes())
        elif pd.api.types.is_numeric_dtype(series):
            parts.append(series.to_numpy().tobytes())
        else:
            parts.append(series.astype(str).to_numpy().tobytes())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _sha256_file(path) -> str:
    from pathlib import Path

    p = Path(path)
    if not p.is_file():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def _feature_version() -> str:
    from tradingbot.ml.research.phase13_9.unified_features import optimized_unified_frame_enabled

    trend_id = resolve_active_trend_engine_id()
    version = resolve_bundle_version()
    opt = "opt" if optimized_unified_frame_enabled() else "leg"
    return f"{trend_id}@{version}:{opt}"


def _dataset_checksum(*, base_dir: str | None, symbol: str, timeframe: str) -> str:
    from tradingbot.ml.dataset.memory_cache import file_fingerprint

    store = DatasetStore(base_dir)
    path = store.resolve_v2_path(symbol, timeframe)
    if not path.is_file():
        return "missing"
    return file_fingerprint(path)


def _pre_top5_frame_checksum(unified: pd.DataFrame) -> str:
    """Checksum of unified frame before top5 attach — used for attach_top5 memoization."""
    cols = [c for c in unified.columns if c not in TOP5_FEATURE_COLUMNS]
    if not cols:
        return unified_frame_sha256(unified)
    return unified_frame_sha256(unified[cols])


@dataclass
class FeatureCacheEntry:
    key: str
    unified: pd.DataFrame
    last_row_index: Any
    unified_sha256: str


@dataclass
class PredictionCacheEntry:
    row_key: str
    unified_signal_checksum: str
    payload: dict[str, Any]


class PipelineCache:
    """Thread-safe singleton cache for registry, bundles, features, predictions."""

    _lock = threading.Lock()
    _registry: EngineRegistry | None = None
    _trend_bundle: TrendRfBundle | None = None
    _phase99_bundle: Any = None
    _feature_cache_slots: OrderedDict[str, FeatureCacheEntry] = OrderedDict()
    _top5_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
    _market_context_cache: OrderedDict[str, Any] = OrderedDict()
    _prediction_cache: dict[str, PredictionCacheEntry] = {}
    _base_dir: str | None = None
    _symbol: str = "XAUUSD"
    _trend_version: str | None = None
    _feature_cache_hits: int = 0
    _feature_cache_misses: int = 0
    _top5_cache_hits: int = 0
    _top5_cache_misses: int = 0
    _market_context_cache_hits: int = 0
    _market_context_cache_misses: int = 0

    @classmethod
    def configure(cls, *, base_dir: str | None = None, symbol: str = "XAUUSD") -> None:
        with cls._lock:
            cls._base_dir = normalize_ml_base_dir(base_dir)
            cls._symbol = symbol

    @classmethod
    def _build_feature_cache_key(
        cls,
        *,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame,
        base_dir: str | None,
    ) -> str:
        closed_ts = resolve_closed_candle_timestamp(candles)
        ds_chk = _dataset_checksum(base_dir=base_dir, symbol=symbol, timeframe=timeframe)
        feat_ver = _feature_version()
        return f"{symbol}|{timeframe}|{closed_ts}|{ds_chk}|{feat_ver}"

    @classmethod
    def _touch_lru(cls, cache: OrderedDict, key: str) -> None:
        cache.move_to_end(key)

    @classmethod
    def _evict_lru(cls, cache: OrderedDict, max_size: int) -> None:
        while len(cache) > max_size:
            cache.popitem(last=False)

    @classmethod
    def get_registry(cls, *, base_dir: str | None = None, symbol: str = "XAUUSD") -> EngineRegistry:
        base_dir = normalize_ml_base_dir(base_dir)
        with cls._lock:
            version = resolve_bundle_version()
            if (
                cls._registry is None
                or (base_dir and base_dir != cls._base_dir)
                or version != cls._trend_version
            ):
                cls._base_dir = base_dir
                cls._symbol = symbol
                cls._trend_version = version
                cls._registry = EngineRegistry.build_default(
                    base_dir=base_dir,
                    build_trend_if_missing=False,
                    symbol=symbol,
                )
            return cls._registry

    @classmethod
    def get_trend_bundle(cls, *, base_dir: str | None = None) -> TrendRfBundle:
        with cls._lock:
            version = resolve_bundle_version()
            if cls._trend_bundle is None or version != cls._trend_version:
                cls._trend_bundle = load_trend_bundle(
                    base_dir=base_dir, build_if_missing=False, version=version,
                )
            return cls._trend_bundle

    @classmethod
    def get_phase99_bundle(cls, *, base_dir: str | None = None) -> Any:
        with cls._lock:
            if cls._phase99_bundle is None:
                cls._phase99_bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
            return cls._phase99_bundle

    @classmethod
    def warm_datasets(
        cls,
        *,
        symbol: str = "XAUUSD",
        timeframes: tuple[str, ...] = ("M5", "M15", "H4"),
        base_dir: str | None = None,
    ) -> dict[str, Any]:
        """Startup warm — load parquet once per symbol/timeframe via DatasetMemoryCache."""
        from tradingbot.ml.dataset.memory_cache import DatasetMemoryCache

        base_dir = normalize_ml_base_dir(base_dir)
        store = DatasetStore(base_dir)
        warmed: list[str] = []
        missing: list[str] = []
        for tf in timeframes:
            df = store.load_v2(symbol, tf)
            if df is None or df.empty:
                missing.append(tf)
            else:
                warmed.append(tf)
        return {
            "symbol": symbol,
            "warmed": warmed,
            "missing": missing,
            "dataset_cache_stats": DatasetMemoryCache.stats(),
        }

    @classmethod
    def get_unified_frame(
        cls,
        candles: pd.DataFrame,
        *,
        base_dir: str | None = None,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
    ) -> pd.DataFrame:
        if candles is None or candles.empty:
            return pd.DataFrame()
        tail = candles.tail(300).copy()
        cache_key = cls._build_feature_cache_key(
            symbol=symbol,
            timeframe=timeframe,
            candles=tail,
            base_dir=base_dir,
        )
        with cls._lock:
            entry = cls._feature_cache_slots.get(cache_key)
            if entry is not None:
                cls._feature_cache_hits += 1
                cls._touch_lru(cls._feature_cache_slots, cache_key)
                return entry.unified

        dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
        unified = build_unified_frame(tail, dataset)
        unified = cls._attach_trend_v41_features(unified, feature_cache_key=cache_key)
        frame_sha = unified_frame_sha256(unified)

        with cls._lock:
            cls._feature_cache_misses += 1
            cls._feature_cache_slots[cache_key] = FeatureCacheEntry(
                key=cache_key,
                unified=unified,
                last_row_index=tail.index[-1],
                unified_sha256=frame_sha,
            )
            cls._touch_lru(cls._feature_cache_slots, cache_key)
            cls._evict_lru(cls._feature_cache_slots, FEATURE_CACHE_MAX_SLOTS)
            return unified

    @classmethod
    def _attach_trend_v41_features(
        cls,
        unified: pd.DataFrame,
        *,
        feature_cache_key: str | None = None,
    ) -> pd.DataFrame:
        """
        Phase 22D — v41 Top5 features require rolling history (Phase 17B training path).
        Single-row attach_top5 produces wrong constants (trend_age=1, swing_efficiency=0).
        """
        if unified.empty:
            return unified
        if resolve_active_trend_engine_id() != TREND_ENGINE_V41_ID:
            return unified
        from tradingbot.ml.research.phase17b.top5_features import attach_top5_features

        if "regime" not in unified.columns:
            from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

            unified = unified.copy()
            unified["regime"] = [rule_classify_row(unified.iloc[i]) for i in range(len(unified))]

        pre_top5_key = f"{feature_cache_key or 'na'}|{_pre_top5_frame_checksum(unified)}|{_feature_version()}"
        with cls._lock:
            cached_top5 = cls._top5_cache.get(pre_top5_key)
            if cached_top5 is not None:
                cls._top5_cache_hits += 1
                cls._touch_lru(cls._top5_cache, pre_top5_key)
                return cached_top5

        attached = attach_top5_features(unified)
        with cls._lock:
            cls._top5_cache_misses += 1
            cls._top5_cache[pre_top5_key] = attached
            cls._touch_lru(cls._top5_cache, pre_top5_key)
            cls._evict_lru(cls._top5_cache, TOP5_CACHE_MAX_SLOTS)
        return attached

    @classmethod
    def get_market_context(
        cls,
        row: pd.Series,
        *,
        symbol: str,
        timeframe: str,
        range_engine: Any,
        trend_engine: Any,
        candles: pd.DataFrame | None = None,
        bar_index: int | None = None,
        base_dir: str | None = None,
    ) -> Any:
        """Memoized build_market_context — one immutable context per closed candle."""
        from tradingbot.ml.decision_engine.validation import build_market_context

        if candles is not None and not candles.empty:
            candle_ts = resolve_closed_candle_timestamp(candles)
        else:
            candle_ts = str(row.get("timestamp", "unknown"))
        row_fp = unified_row_fingerprint(row)
        model_fp = cls._model_fingerprint(base_dir=base_dir)
        bar_fp = str(bar_index) if bar_index is not None else "none"
        cache_key = f"{symbol}|{timeframe}|{candle_ts}|{row_fp}|{model_fp}|{bar_fp}"

        with cls._lock:
            cached = cls._market_context_cache.get(cache_key)
            if cached is not None:
                cls._market_context_cache_hits += 1
                cls._touch_lru(cls._market_context_cache, cache_key)
                return copy.deepcopy(cached)

        ctx = build_market_context(
            row,
            symbol=symbol,
            timeframe=timeframe,
            range_engine=range_engine,
            trend_engine=trend_engine,
            candles=candles,
            bar_index=bar_index,
        )
        with cls._lock:
            cls._market_context_cache_misses += 1
            cls._market_context_cache[cache_key] = ctx
            cls._touch_lru(cls._market_context_cache, cache_key)
            cls._evict_lru(cls._market_context_cache, MARKET_CONTEXT_CACHE_MAX_SLOTS)
        return ctx

    @classmethod
    def build_prediction_cache_key(
        cls,
        *,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame,
        unified_row: pd.Series,
        base_dir: str | None = None,
    ) -> str:
        """
        Stable prediction cache key for one closed candle evaluation.

        Components: symbol, timeframe, closed-candle timestamp, unified-row fingerprint,
        active model bundle fingerprint. Never uses dataframe positional index.
        """
        candle_ts = resolve_closed_candle_timestamp(candles)
        feature_fp = unified_row_fingerprint(unified_row)
        model_fp = cls._model_fingerprint(base_dir=base_dir)
        return f"{symbol}|{timeframe}|{candle_ts}|{feature_fp}|{model_fp}"

    @classmethod
    def _model_fingerprint(cls, *, base_dir: str | None = None) -> str:
        trend_id = resolve_active_trend_engine_id()
        trend_version = resolve_bundle_version()
        trend_chk = ""
        try:
            bundle = cls.get_trend_bundle(base_dir=base_dir)
            if bundle.checksum:
                trend_chk = str(bundle.checksum.get("model.pkl", ""))[:12]
        except Exception:
            trend_chk = ""
        phase99_chk = _sha256_file(phase9_9_model_path(base_dir))
        return f"{trend_id}@{trend_version}:{trend_chk}:{phase99_chk}"

    @classmethod
    def cache_stats(cls) -> dict[str, Any]:
        with cls._lock:
            feat_total = cls._feature_cache_hits + cls._feature_cache_misses
            top5_total = cls._top5_cache_hits + cls._top5_cache_misses
            ctx_total = cls._market_context_cache_hits + cls._market_context_cache_misses
            return {
                "feature_cache_slots": len(cls._feature_cache_slots),
                "feature_cache_hits": cls._feature_cache_hits,
                "feature_cache_misses": cls._feature_cache_misses,
                "feature_cache_hit_ratio": round(cls._feature_cache_hits / feat_total, 4) if feat_total else 0.0,
                "top5_cache_slots": len(cls._top5_cache),
                "top5_cache_hits": cls._top5_cache_hits,
                "top5_cache_misses": cls._top5_cache_misses,
                "top5_cache_hit_ratio": round(cls._top5_cache_hits / top5_total, 4) if top5_total else 0.0,
                "market_context_cache_slots": len(cls._market_context_cache),
                "market_context_cache_hits": cls._market_context_cache_hits,
                "market_context_cache_misses": cls._market_context_cache_misses,
                "market_context_hit_ratio": round(cls._market_context_cache_hits / ctx_total, 4) if ctx_total else 0.0,
            }

    @classmethod
    def prediction_cache_size(cls) -> int:
        with cls._lock:
            return len(cls._prediction_cache)

    @classmethod
    def list_prediction_keys(cls) -> list[str]:
        with cls._lock:
            return list(cls._prediction_cache.keys())

    @classmethod
    def get_prediction(cls, row_key: str) -> dict[str, Any] | None:
        with cls._lock:
            entry = cls._prediction_cache.get(row_key)
            return dict(entry.payload) if entry else None

    @classmethod
    def set_prediction(cls, row_key: str, checksum: str, payload: dict[str, Any]) -> None:
        with cls._lock:
            cls._prediction_cache[row_key] = PredictionCacheEntry(
                row_key=row_key, unified_signal_checksum=checksum, payload=payload,
            )
            if len(cls._prediction_cache) > 256:
                oldest = next(iter(cls._prediction_cache))
                del cls._prediction_cache[oldest]

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._registry = None
            cls._trend_bundle = None
            cls._phase99_bundle = None
            cls._feature_cache_slots.clear()
            cls._top5_cache.clear()
            cls._market_context_cache.clear()
            cls._prediction_cache.clear()
            cls._trend_version = None
            cls._feature_cache_hits = 0
            cls._feature_cache_misses = 0
            cls._top5_cache_hits = 0
            cls._top5_cache_misses = 0
            cls._market_context_cache_hits = 0
            cls._market_context_cache_misses = 0
