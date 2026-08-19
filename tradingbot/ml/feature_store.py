"""Phase 11A — institutional-grade unified ML feature store."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.market_filters import atr_percentile, compute_adx
from tradingbot.domain.price_action import (
    _liquidity_sweep,
    enrich_price_action,
    infer_trend,
)
from tradingbot.ml.features.base import normalize_atr_distance, safe_float, truncated_df
from tradingbot.ml.features.context import HtfContextFeatures
from tradingbot.ml.features.microstructure import MicrostructureFeatures
from tradingbot.ml.features.price_action import PriceActionFeatures
from tradingbot.ml.features.session import SessionFeatures
from tradingbot.ml.features.smc import SmcStructureFeatures
from tradingbot.ml.features.volatility import VolatilityFeatures
from tradingbot.strategies.vol_context_engine import evaluate_vol_context_df

SCHEMA_VERSION = "11a_v1"

FEATURES: list[str] = [
    "atr_pct",
    "atr_percentile_20",
    "atr_percentile_50",
    "ema20_50_sep_pct",
    "h1_trend",
    "h4_trend",
    "session_london",
    "session_ny",
    "session_overlap",
    "spread_pips",
    "spread_regime",
    "tick_volume_ratio",
    "previous_bar_range",
    "sweep_high",
    "sweep_low",
    "bos_distance_atr",
    "fvg_size_atr",
    "candle_body_pct",
    "wick_upper_pct",
    "wick_lower_pct",
    "hour_sin",
    "hour_cos",
    "weekday",
    "regime_code",
    "quality_score",
]

REGIME_LABEL_MAP = {"RANGING": 0.0, "TREND": 1.0, "EXPANSION": 2.0}


def feature_names() -> list[str]:
    return list(FEATURES)


def schema_hash(*, version: str = SCHEMA_VERSION) -> str:
    payload = json.dumps({"version": version, "features": FEATURES}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def classify_regime(adx: float, atr_pct: float, *, expansion_min: float = 70.0) -> str:
    """Causal regime bucket for dataset splitting."""
    if atr_pct >= expansion_min and adx < 28.0:
        return "EXPANSION"
    if adx >= 25.0:
        return "TREND"
    return "RANGING"


def _h1_trend(work: pd.DataFrame) -> float:
    if work is None or len(work) < 120:
        return 0.0
    h1 = (
        work.resample("1h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )
    if len(h1) < 25:
        return 0.0
    close = h1["close"].astype(float)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    if ema20.iloc[-1] > ema50.iloc[-1]:
        return 1.0
    if ema20.iloc[-1] < ema50.iloc[-1]:
        return -1.0
    return 0.0


def _rolling_atr_percentile(work: pd.DataFrame, window: int) -> float:
    if work is None or len(work) < window + 14:
        return 50.0
    atr = _atr_series(work)
    tail = atr.tail(window).dropna()
    if tail.empty:
        return 50.0
    current = safe_float(atr.iloc[-1], 0.0)
    if current <= 0:
        return 50.0
    rank = (tail <= current).sum() / max(len(tail), 1)
    return round(float(rank * 100.0), 4)


def _spread_regime(spread_z: float) -> float:
    if spread_z <= -0.5:
        return 0.0
    if spread_z >= 2.0:
        return 2.0
    if spread_z >= 1.0:
        return 1.5
    return 1.0


def _sweep_flags(work: pd.DataFrame, swings: list, index: int) -> tuple[float, float]:
    if work is None or len(work) < 3 or not swings:
        return 0.0, 0.0
    row = work.iloc[index]
    highs = [s.price for s in swings if s.kind == "high" and s.index < index][-3:]
    lows = [s.price for s in swings if s.kind == "low" and s.index < index][-3:]
    sweep_high = 1.0 if highs and float(row["high"]) > max(highs) and float(row["close"]) < max(highs) else 0.0
    sweep_low = 1.0 if lows and float(row["low"]) < min(lows) and float(row["close"]) > min(lows) else 0.0
    return sweep_high, sweep_low


def _fvg_size_atr(fvgs: list, price: float, atr: float, index: int) -> float:
    if atr <= 0 or not fvgs:
        return 0.0
    best = 0.0
    for gap in reversed(fvgs):
        if gap.index > index or gap.filled:
            continue
        if gap.bottom <= price <= gap.top:
            best = max(best, abs(gap.top - gap.bottom) / atr)
            break
    return round(best, 4)


def sanitize_features(features: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in FEATURES:
        val = features.get(name, 0.0)
        if val is None:
            val = 0.0
        elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            val = 0.0
        else:
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = 0.0
            if math.isnan(val) or math.isinf(val):
                val = 0.0
        out[name] = val
    return out


def to_vector(features: dict[str, Any]) -> list[float]:
    clean = sanitize_features(features)
    return [clean[name] for name in FEATURES]


def compute_at(
    df: pd.DataFrame,
    index: int,
    *,
    symbol: str = "XAUUSD",
    h4_df: pd.DataFrame | None = None,
    spread_series: pd.Series | None = None,
    regime: str | None = None,
) -> dict[str, float]:
    """Build institutional feature vector at bar index (causal, no leakage)."""
    work = truncated_df(df, index)
    if work is None or len(work) < 30:
        return sanitize_features({})

    pa_cfg = get_price_action_config(symbol, "M5")
    i = len(work) - 1
    row = work.iloc[i]
    atr = safe_float(_atr_series(work).iloc[-1], max(float(row["close"]) * 0.001, 1e-9))

    vol = VolatilityFeatures().compute_features(df, index)
    sess = SessionFeatures().compute_features(df, index, symbol=symbol)
    pa = PriceActionFeatures().compute_features(df, index)
    micro = MicrostructureFeatures().compute_features(df, index, spread_series=spread_series)
    smc = SmcStructureFeatures().compute_features(df, index, pa_cfg=pa_cfg)
    ctx = HtfContextFeatures().compute_features(df, index, symbol=symbol, h4_df=h4_df)

    enriched = enrich_price_action(work, pa_cfg, at_index=i)
    swings = enriched.attrs.get("pa_swings") or []
    breaks = enriched.attrs.get("pa_breaks") or []
    fvgs = enriched.attrs.get("pa_fvgs") or []

    atr_pct = safe_float(vol.get("atr_percentile", 50.0), 50.0)
    adx = compute_adx(work)
    regime_name = regime or classify_regime(adx, atr_pct)

    ts = work.index[-1]
    hour = float(ts.hour) if hasattr(ts, "hour") else 12.0
    weekday = float(ts.weekday()) if hasattr(ts, "weekday") else 2.0

    overlap = 1.0 if 12 <= hour < 17 else 0.0
    sweep_high, sweep_low = _sweep_flags(work, swings, i)

    prev_range = 0.0
    if len(work) >= 2:
        prev = work.iloc[-2]
        prev_range = safe_float((prev["high"] - prev["low"]) / max(atr, 1e-9), 0.0)

    bos_distance = 999.0
    if breaks:
        last = breaks[-1]
        bos_distance = safe_float(abs(i - last.index) / max(atr, 1e-9), 0.0)
        if hasattr(last, "level"):
            bos_distance = abs(normalize_atr_distance(float(row["close"]), float(last.level), atr))

    close = float(row["close"])
    ema20 = work["close"].astype(float).ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = work["close"].astype(float).ewm(span=50, adjust=False).mean().iloc[-1]
    ema_sep = safe_float((ema20 - ema50) / max(close, 1e-9) * 100.0, 0.0)

    try:
        vol_ctx = evaluate_vol_context_df(work, i)
        quality = vol_ctx.quality_score()
    except Exception:
        quality = float(np.clip(0.35 * (atr_pct / 100.0) + 0.25 * overlap + 0.25 * sess.get("session_london", 0), 0, 1))

    h4_trend = safe_float(ctx.get("h4_trend_bias", 0.0), 0.0)

    out = {
        "atr_pct": round(atr_pct, 4),
        "atr_percentile_20": _rolling_atr_percentile(work, 20),
        "atr_percentile_50": _rolling_atr_percentile(work, 50),
        "ema20_50_sep_pct": round(ema_sep, 4),
        "h1_trend": _h1_trend(work),
        "h4_trend": h4_trend,
        "session_london": sess.get("session_london", 0.0),
        "session_ny": sess.get("session_ny", 0.0),
        "session_overlap": overlap,
        "spread_pips": micro.get("spread_pips", 0.0),
        "spread_regime": _spread_regime(micro.get("spread_zscore", 0.0)),
        "tick_volume_ratio": micro.get("tick_volume_proxy", 0.0),
        "previous_bar_range": round(prev_range, 4),
        "sweep_high": sweep_high,
        "sweep_low": sweep_low,
        "bos_distance_atr": round(bos_distance, 4),
        "fvg_size_atr": _fvg_size_atr(fvgs, close, atr, i),
        "candle_body_pct": pa.get("body_ratio", 0.0),
        "wick_upper_pct": pa.get("upper_wick_ratio", 0.0),
        "wick_lower_pct": pa.get("lower_wick_ratio", 0.0),
        "hour_sin": round(math.sin(2 * math.pi * hour / 24.0), 4),
        "hour_cos": round(math.cos(2 * math.pi * hour / 24.0), 4),
        "weekday": weekday,
        "regime_code": REGIME_LABEL_MAP.get(regime_name, 0.0),
        "quality_score": round(quality, 4),
    }
    return sanitize_features(out)


def build_dataframe(
    df: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    h4_df: pd.DataFrame | None = None,
    spread_series: pd.Series | None = None,
    indices: list[int] | None = None,
    start_index: int = 60,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=FEATURES)
    idx_list = indices or list(range(max(start_index, 60), len(df)))
    rows: list[dict[str, float]] = []
    index_out: list = []
    for i in idx_list:
        if i < 0 or i >= len(df):
            continue
        rows.append(
            compute_at(df, i, symbol=symbol, h4_df=h4_df, spread_series=spread_series)
        )
        index_out.append(df.index[i])
    out = pd.DataFrame(rows, index=pd.DatetimeIndex(index_out, tz="UTC"))
    out.index.name = "time"
    return out


def parity_vs_legacy(
    ml_kernel_features: list[str],
    meta_features: list[str],
) -> dict[str, Any]:
    canonical = set(FEATURES)
    ml_set = set(ml_kernel_features)
    meta_set = set(meta_features)
    missing_ml = sorted(canonical - ml_set)
    missing_meta = sorted(canonical - meta_set)
    overlap_ml = len(canonical & ml_set)
    overlap_meta = len(canonical & meta_set)
    return {
        "canonical_count": len(FEATURES),
        "ml_kernel_features": ml_kernel_features,
        "meta_labeler_features": meta_features,
        "missing_in_ml_kernel": missing_ml,
        "missing_in_meta_labeler": missing_meta,
        "parity_score_ml": round(overlap_ml / len(FEATURES) * 100, 2),
        "parity_score_meta": round(overlap_meta / len(FEATURES) * 100, 2),
    }


class InstitutionalFeatureStore:
    """Facade for Phase 11A institutional ML pipeline."""

    FEATURES = FEATURES
    SCHEMA_VERSION = SCHEMA_VERSION

    feature_names = staticmethod(feature_names)
    schema_hash = staticmethod(schema_hash)
    sanitize_features = staticmethod(sanitize_features)
    to_vector = staticmethod(to_vector)
    compute_at = staticmethod(compute_at)
    build_dataframe = staticmethod(build_dataframe)
    classify_regime = staticmethod(classify_regime)
    parity_vs_legacy = staticmethod(parity_vs_legacy)
