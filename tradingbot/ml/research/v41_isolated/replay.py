"""Phase 1.5.37 — isolated TREND-only v41 replay (offline, no live imports)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, load_trend_bundle
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase14_4.config import DEFAULT_RR, MAX_HOLD_BARS
from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
from tradingbot.ml.research.regime_detector.regime_classifier import (
    ADX_RANGE_MAX,
    ADX_TREND_MIN,
    ATR_EXTREME,
    ATR_HIGH_VOL,
    ATR_LOW_VOL,
    EMA_SLOPE_STRONG,
    SPREAD_ABNORMAL,
    rule_classify_row,
)
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_strategy.trend_signal import RR_RATIO, SL_ATR_MULT, build_trend_signal
from tradingbot.ml.research.v41_isolated.integrity import audit_v41_bundle

FREEZE_START = pd.Timestamp("2023-09-19T05:25:00+00:00")
FREEZE_END = pd.Timestamp("2025-08-18T01:20:00+00:00")
DEFAULT_WARMUP_START = pd.Timestamp("2023-08-01T00:00:00+00:00")
MIN_TRADES_FOR_INFERENCE = 30


def vectorized_rule_classify(frame: pd.DataFrame) -> np.ndarray:
    """Same cascade as rule_classify_row, vectorized for offline replay scale."""
    n = len(frame)
    spread = frame["spread_pips"].astype(float).to_numpy() if "spread_pips" in frame.columns else np.zeros(n)
    atr_pct = frame["atr_percentile"].astype(float).fillna(50.0).to_numpy() if "atr_percentile" in frame.columns else np.full(n, 50.0)
    adx = frame["adx"].astype(float).fillna(0.0).to_numpy() if "adx" in frame.columns else np.zeros(n)
    slope = frame["ema50_slope"].astype(float).fillna(0.0).to_numpy() if "ema50_slope" in frame.columns else np.zeros(n)
    vol = frame["volatility"].astype(float).fillna(0.0).to_numpy() if "volatility" in frame.columns else np.zeros(n)
    out = np.full(n, "RANGE", dtype=object)
    rest = np.ones(n, dtype=bool)
    no_trade = (spread >= SPREAD_ABNORMAL) | (atr_pct >= ATR_EXTREME) | (vol >= 5.0)
    out[no_trade] = "NO_TRADE"
    rest &= ~no_trade
    high_vol = rest & (atr_pct > ATR_HIGH_VOL)
    out[high_vol] = "HIGH_VOLATILITY"
    rest &= ~high_vol
    trend_strong = rest & (adx > ADX_TREND_MIN) & (np.abs(slope) >= EMA_SLOPE_STRONG)
    out[trend_strong] = "TREND"
    rest &= ~trend_strong
    quiet = rest & (adx < ADX_RANGE_MAX) & (atr_pct < ATR_LOW_VOL)
    out[quiet] = "RANGE"
    rest &= ~quiet
    out[rest & (adx > ADX_TREND_MIN)] = "TREND"
    return out


def vectorized_variant_a(frame: pd.DataFrame) -> np.ndarray:
    """Same rules as evaluate_variant_a for regime==TREND rows."""
    n = len(frame)
    out = np.full(n, "HOLD", dtype=object)
    if n == 0:
        return out
    ema20 = frame["ema20"].astype(float).to_numpy() if "ema20" in frame.columns else np.zeros(n)
    ema50 = frame["ema50"].astype(float).to_numpy() if "ema50" in frame.columns else np.zeros(n)
    slope = frame["ema50_slope"].astype(float).to_numpy() if "ema50_slope" in frame.columns else np.zeros(n)
    adx = frame["adx"].astype(float).to_numpy() if "adx" in frame.columns else np.zeros(n)
    hh = frame["higher_high_count"].fillna(0).astype(int).to_numpy() if "higher_high_count" in frame.columns else np.zeros(n, dtype=int)
    ll = frame["lower_low_count"].fillna(0).astype(int).to_numpy() if "lower_low_count" in frame.columns else np.zeros(n, dtype=int)
    tradable = adx > 25.0
    buy = tradable & (ema20 > ema50) & (slope > 0) & ((hh >= 2) | (hh > ll))
    sell = tradable & (ema20 < ema50) & (slope < 0) & ((ll >= 2) | (ll > hh))
    out[buy] = "BUY"
    out[sell] = "SELL"
    return out


def _prepare_ohlc(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    return c.sort_index()


def simulate_r_from_levels(
    candles: pd.DataFrame,
    bar_index: int,
    *,
    direction: str,
    sl: float,
    tp: float,
    max_hold: int = MAX_HOLD_BARS,
) -> dict[str, Any]:
    """Forward-only SL/TP walk. Same-bar SL and TP: SL wins (conservative)."""
    if direction not in ("BUY", "SELL") or bar_index >= len(candles) - 1:
        return {"r_multiple": 0.0, "hold_bars": 0, "exit": "none"}
    entry = float(candles.iloc[bar_index]["close"])
    r_unit = abs(entry - float(sl))
    if r_unit <= 0:
        return {"r_multiple": 0.0, "hold_bars": 0, "exit": "invalid_sl"}
    end = min(bar_index + max_hold, len(candles) - 1)
    for j in range(bar_index + 1, end + 1):
        hi = float(candles.iloc[j]["high"])
        lo = float(candles.iloc[j]["low"])
        if direction == "BUY":
            if lo <= sl:
                return {"r_multiple": -1.0, "hold_bars": j - bar_index, "exit": "sl"}
            if hi >= tp:
                return {"r_multiple": round((tp - entry) / r_unit, 4), "hold_bars": j - bar_index, "exit": "tp"}
        else:
            if hi >= sl:
                return {"r_multiple": -1.0, "hold_bars": j - bar_index, "exit": "sl"}
            if lo <= tp:
                return {"r_multiple": round((entry - tp) / r_unit, 4), "hold_bars": j - bar_index, "exit": "tp"}
    close = float(candles.iloc[end]["close"])
    if direction == "BUY":
        exit_r = (close - entry) / r_unit
    else:
        exit_r = (entry - close) / r_unit
    return {"r_multiple": round(float(exit_r), 4), "hold_bars": end - bar_index, "exit": "timeout"}


def _batch_probs(bundle: TrendRfBundle, frame: pd.DataFrame) -> np.ndarray:
    X = frame.reindex(columns=bundle.feature_order).astype(float).fillna(0.0)
    Xs = bundle.scaler.transform(X)
    return bundle.model.predict_proba(Xs)[:, 1]


def _split_label(ts: pd.Timestamp) -> str:
    if ts < FREEZE_START:
        return "pre_train"
    if ts <= FREEZE_END:
        return "in_sample"
    return "oos"


def summarize_r(returns: list[float]) -> dict[str, Any]:
    arr = np.asarray(returns, dtype=float)
    n = int(len(arr))
    if n == 0:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "total_r": 0.0,
            "average_r": None,
            "expectancy": None,
            "profit_factor": None,
            "max_drawdown_r": 0.0,
            "sharpe": None,
            "meaningful": False,
        }
    wins = int(np.sum(arr > 0))
    losses = int(np.sum(arr < 0))
    gains = float(arr[arr > 0].sum())
    loss_abs = float(-arr[arr < 0].sum())
    if loss_abs <= 0:
        pf = None if gains <= 0 else float("inf")
    else:
        pf = round(gains / loss_abs, 6)
    eq = np.cumsum(arr)
    peak = np.maximum.accumulate(eq)
    dd = float(np.min(eq - peak))
    sharpe = None
    if n >= MIN_TRADES_FOR_INFERENCE and float(np.std(arr)) > 1e-12:
        sharpe = round(float(np.mean(arr) / np.std(arr)), 6)
    return {
        "trades": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n, 6),
        "total_r": round(float(arr.sum()), 4),
        "average_r": round(float(arr.mean()), 6),
        "expectancy": round(float(arr.mean()), 6),
        "profit_factor": pf,
        "max_drawdown_r": round(dd, 4),
        "sharpe": sharpe,
        "meaningful": n >= MIN_TRADES_FOR_INFERENCE,
    }


def run_isolated_trend_replay(
    candles: pd.DataFrame,
    *,
    bundle: TrendRfBundle | None = None,
    symbol: str = "XAUUSD",
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    non_overlapping: bool = True,
    max_hold: int = MAX_HOLD_BARS,
) -> dict[str, Any]:
    """TREND-only v41 replay. Offline research path; no execution adapters."""
    integrity = audit_v41_bundle()
    bundle = bundle or load_trend_bundle(version="v41")
    ohlc = _prepare_ohlc(candles)
    start = start or DEFAULT_WARMUP_START
    end = end or ohlc.index.max()
    window = ohlc.loc[(ohlc.index >= start) & (ohlc.index <= end)]
    if window.empty:
        return {"ok": False, "error": "no_candles_in_window", "integrity": integrity}

    features = build_ml_features(window)
    features["timestamp"] = pd.to_datetime(features["timestamp"], utc=True)
    features = features.copy()
    features["regime"] = vectorized_rule_classify(features)
    unified = attach_top5_features(features)
    missing = [f for f in bundle.feature_order if f not in unified.columns]
    if missing:
        return {"ok": False, "error": "feature_contract_broken", "missing": missing, "integrity": integrity}

    ts = pd.to_datetime(unified["timestamp"], utc=True)
    eval_mask = ts >= FREEZE_START
    trend_mask = eval_mask & (unified["regime"].astype(str) == "TREND")
    trend_idx = np.flatnonzero(trend_mask.to_numpy())
    if len(trend_idx) == 0:
        return {
            "ok": True,
            "integrity": integrity,
            "classification": {
                "trend_observations": 0,
                "rule_signals": 0,
                "accepted_trades": 0,
                "non_trend_observations": int(eval_mask.sum()),
            },
            "book": summarize_r([]),
            "trades": [],
        }

    trend_frame = unified.iloc[trend_idx]
    directions = vectorized_variant_a(trend_frame)
    directed = directions != "HOLD"
    blocked_hold = int((~directed).sum())
    directed_idx = trend_idx[directed]
    directed_frame = unified.iloc[directed_idx]
    directed_dirs = directions[directed]
    threshold = float(bundle.config.get("threshold", 0.4))
    probs = _batch_probs(bundle, directed_frame) if len(directed_frame) else np.array([])
    above = probs >= threshold if len(probs) else np.array([], dtype=bool)
    blocked_prob = int((~above).sum()) if len(above) else 0

    ts_to_bar = {pd.Timestamp(t): i for i, t in enumerate(window.index)}
    trades: list[dict[str, Any]] = []
    overlapping_accepted = 0
    next_free_bar = -1

    for j, i in enumerate(directed_idx):
        if not bool(above[j]):
            continue
        direction = str(directed_dirs[j])
        row = unified.iloc[i]
        ts_i = pd.Timestamp(row["timestamp"])
        bar_idx = ts_to_bar.get(ts_i)
        if bar_idx is None:
            continue
        overlapping_accepted += 1
        if non_overlapping and bar_idx < next_free_bar:
            continue
        levels = build_trend_signal(row, symbol=symbol, direction=direction)
        outcome = simulate_r_from_levels(
            window,
            bar_idx,
            direction=direction,
            sl=float(levels["stop_loss"]),
            tp=float(levels["take_profit"]),
            max_hold=max_hold,
        )
        hold = int(outcome["hold_bars"])
        next_free_bar = bar_idx + hold + 1
        r_mult = float(outcome["r_multiple"])
        trades.append({
            "timestamp": ts_i.isoformat(),
            "split": _split_label(ts_i),
            "direction": direction,
            "probability": round(float(probs[j]), 6),
            "r_multiple": r_mult,
            "hold_bars": hold,
            "exit": outcome["exit"],
            "engine": "trend_rf_v41",
            "regime": "TREND",
            "rr_ratio": float(levels.get("rr_ratio", RR_RATIO)),
            "sl_atr_mult": SL_ATR_MULT,
            "pseudo_return_used": False,
        })

    rs = [t["r_multiple"] for t in trades]
    in_s = [t["r_multiple"] for t in trades if t["split"] == "in_sample"]
    oos = [t["r_multiple"] for t in trades if t["split"] == "oos"]
    return {
        "ok": True,
        "integrity": integrity,
        "methodology": {
            "engine": "trend_rf_v41",
            "regime_filter": "rule_classify_row == TREND",
            "direction_rule": "evaluate_variant_a",
            "threshold": threshold,
            "sl_tp": f"ATR*{SL_ATR_MULT} SL, RR={DEFAULT_RR} via build_trend_signal",
            "max_hold_bars": max_hold,
            "non_overlapping": non_overlapping,
            "pseudo_return": False,
            "range_mixed": False,
            "costs_slippage": "NOT_APPLIED — existing ATR SL/TP path has no spread/slippage",
            "downsample_19a": False,
        },
        "coverage": {
            "bars_in_window": int(len(window)),
            "unified_rows": int(len(unified)),
            "start": str(window.index.min()),
            "end": str(window.index.max()),
            "freeze_start": FREEZE_START.isoformat(),
            "freeze_end": FREEZE_END.isoformat(),
        },
        "classification": {
            "eval_observations": int(eval_mask.sum()),
            "trend_observations": int(len(trend_idx)),
            "non_trend_observations": int(eval_mask.sum()) - int(len(trend_idx)),
            "rule_signals": int(len(directed_idx)),
            "rule_hold": blocked_hold,
            "below_threshold": blocked_prob,
            "overlapping_accepted": overlapping_accepted,
            "accepted_trades": len(trades),
            "rejected_filtered": blocked_hold + blocked_prob + max(0, overlapping_accepted - len(trades)),
        },
        "average_holding_bars": (
            round(float(np.mean([t["hold_bars"] for t in trades])), 4) if trades else None
        ),
        "trade_date_range": {
            "first": trades[0]["timestamp"] if trades else None,
            "last": trades[-1]["timestamp"] if trades else None,
        },
        "book": summarize_r(rs),
        "book_in_sample": summarize_r(in_s),
        "book_oos": summarize_r(oos),
        "bundle_classification_metrics": {
            "source": "training_manifest.json — NOT trading performance",
            "timeseries_cv_mean_auc": (bundle.metadata or {}).get("timeseries_cv_mean_auc"),
            "note": "AUC is a classification metric. Do not treat as PF/expectancy.",
        },
        "trades": trades,
    }
