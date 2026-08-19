"""Phase 16D — compute candidate feature values from unified frame (research only)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row


def _hurst_proxy(series: pd.Series, window: int = 50) -> pd.Series:
    def _h(chunk: np.ndarray) -> float:
        if len(chunk) < 10:
            return 0.5
        mean = np.mean(chunk)
        dev = np.cumsum(chunk - mean)
        r = np.max(dev) - np.min(dev)
        s = np.std(chunk)
        if s < 1e-12:
            return 0.5
        rs = r / s
        return float(np.clip(np.log(rs + 1) / np.log(len(chunk)), 0.0, 1.0))

    rets = series.pct_change().fillna(0.0)
    return rets.rolling(window, min_periods=10).apply(_h, raw=True).fillna(0.5)


def _fractal_dim_proxy(series: pd.Series, window: int = 30) -> pd.Series:
    def _fd(chunk: np.ndarray) -> float:
        if len(chunk) < 5:
            return 1.0
        path = np.sum(np.abs(np.diff(chunk)))
        direct = abs(chunk[-1] - chunk[0]) + 1e-12
        return float(np.clip(path / direct, 1.0, 3.0))

    return series.rolling(window, min_periods=5).apply(_fd, raw=True).fillna(1.0)


def compute_candidate_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive candidate features on a copy — never writes to production pipeline."""
    df = frame.copy()
    close = df["close"].astype(float) if "close" in df.columns else pd.Series(0.0, index=df.index)
    atr = df["atr"].astype(float) if "atr" in df.columns else pd.Series(1.0, index=df.index)
    adx = df["adx"].astype(float) if "adx" in df.columns else pd.Series(0.0, index=df.index)
    rsi = df["rsi"].astype(float) if "rsi" in df.columns else pd.Series(50.0, index=df.index)
    macd = df["macd_histogram"].astype(float) if "macd_histogram" in df.columns else pd.Series(0.0, index=df.index)
    ema20 = df["ema20"].astype(float) if "ema20" in df.columns else close
    ema50_slope = df["ema50_slope"].astype(float) if "ema50_slope" in df.columns else pd.Series(0.0, index=df.index)
    mom = df["candle_momentum"].astype(float) if "candle_momentum" in df.columns else pd.Series(0.0, index=df.index)
    breakout = df["breakout_distance"].astype(float) if "breakout_distance" in df.columns else pd.Series(0.0, index=df.index)

    rule_dirs = [
        evaluate_variant_a(df.iloc[i], regime=rule_classify_row(df.iloc[i]))
        for i in range(len(df))
    ]
    df["_rule_dir"] = rule_dirs

    persistence = []
    age = []
    cur_p = 0
    cur_age = 0
    last_dir = "HOLD"
    regimes = [rule_classify_row(df.iloc[i]) for i in range(len(df))]
    for idx, d in enumerate(rule_dirs):
        if d in ("BUY", "SELL") and d == last_dir:
            cur_p += 1
        elif d in ("BUY", "SELL"):
            cur_p = 1
            last_dir = d
        else:
            cur_p = 0
            last_dir = "HOLD"
        persistence.append(cur_p)
        if regimes[idx] == "TREND":
            cur_age += 1
        else:
            cur_age = 0
        age.append(cur_age)
    df["trend_persistence"] = persistence
    df["trend_age"] = age

    df["momentum_acceleration"] = mom.diff().fillna(0.0)
    df["slope_acceleration"] = ema50_slope.diff().fillna(0.0)
    atr_ma = atr.rolling(20, min_periods=5).mean().replace(0, np.nan)
    df["atr_expansion_ratio"] = (atr / atr_ma).fillna(1.0)
    if "volume" in df.columns:
        vol = df["volume"].astype(float)
        df["volume_expansion"] = (vol / vol.rolling(20, min_periods=5).mean().replace(0, np.nan)).fillna(1.0)
    else:
        df["volume_expansion"] = 1.0

    disp = close.diff(10).abs()
    df["swing_efficiency"] = (disp / atr.replace(0, np.nan)).fillna(0.0)
    df["fractal_dimension_proxy"] = _fractal_dim_proxy(close)
    df["hurst_proxy"] = _hurst_proxy(close)
    df["adx_acceleration"] = adx.diff().fillna(0.0)

    ema50 = df["ema50"].astype(float) if "ema50" in df.columns else close
    ema200 = df["ema200"].astype(float) if "ema200" in df.columns else close
    signs = np.sign(ema20 - ema50) + np.sign(ema50 - ema200) + np.sign(ema20 - ema200)
    df["mtf_agreement"] = signs / 3.0
    df["ema_curvature"] = ema20.diff().diff().fillna(0.0)
    df["macd_slope"] = macd.diff().fillna(0.0)
    df["rsi_velocity"] = rsi.diff().fillna(0.0)
    df["breakout_quality"] = breakout * (adx / 50.0)
    vwap_proxy = (close * (df["volume"].astype(float) if "volume" in df.columns else 1.0)).rolling(20, min_periods=5).mean()
    vol_sum = (df["volume"].astype(float) if "volume" in df.columns else pd.Series(1.0, index=df.index)).rolling(20, min_periods=5).sum()
    vwap = vwap_proxy / vol_sum.replace(0, np.nan)
    df["distance_from_vwap_proxy"] = ((close - vwap) / atr.replace(0, np.nan)).fillna(0.0)

    df.drop(columns=["_rule_dir"], inplace=True, errors="ignore")
    return df


CANDIDATE_FEATURE_IDS: tuple[str, ...] = (
    "trend_persistence", "trend_age", "momentum_acceleration", "slope_acceleration",
    "atr_expansion_ratio", "volume_expansion", "swing_efficiency", "fractal_dimension_proxy",
    "hurst_proxy", "adx_acceleration", "mtf_agreement", "ema_curvature", "macd_slope",
    "rsi_velocity", "breakout_quality", "distance_from_vwap_proxy",
)
