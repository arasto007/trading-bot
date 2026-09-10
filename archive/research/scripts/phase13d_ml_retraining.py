#!/usr/bin/env python3
"""
PHASE 13D - ML data expansion and regime model retraining (RESEARCH/TRAINING ONLY).

No live ML enable, no router changes, no orders.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
    "TRADINGBOT_DRY_RUN": "1",
})
warnings.filterwarnings("ignore")

SYMBOL = "XAUUSD"
WINDOWS = (30, 60, 90, 180)
HOLDING_BARS_M5 = 48
TAIL_BARS = 280
WARMUP = 500
EVAL_TF = "5m"
DECISION_THRESHOLD = 0.52
PSI_BINS = 10

DATA_DIR = ROOT / "data" / "ml" / "research" / "phase13d"
MODEL_DIR = DATA_DIR / "models"
LOG_DIR = ROOT / "logs" / "phase13d"
REPORT_PATH = ROOT / "logs" / "phase13d_ml_retraining.txt"
CACHE_DIR = ROOT / "data" / "cache"
PHASE12A_LABELED = ROOT / "data" / "ml" / "research" / "phase12a" / "pa_setups_labeled.parquet"
PHASE12A_RAW = ROOT / "data" / "ml" / "research" / "phase12a" / "pa_setups_raw.parquet"

GATE = {
    "samples": 300,
    "oos_pf": 1.25,
    "oos_expectancy_r": 0.15,
    "precision_buy": 0.58,
    "precision_sell": 0.58,
    "brier_score": 0.12,
    "psi": 0.25,
}

REGIMES = ("TREND", "EXPANSION", "RANGING")


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5_parquet(days: int) -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    path = CACHE_DIR / f"XAUUSD_M5_{days}d.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"Missing cache: {path}")
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df["volume"] = df["tick_volume"]
    df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    return prepare_indicator_frame(df)


def ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def resample_h4(df: pd.DataFrame) -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    agg = (
        df.resample("4h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    return prepare_indicator_frame(agg)


def session_name_from_hour(hour: int) -> str:
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 17:
        return "overlap"
    if 17 <= hour < 22:
        return "ny"
    if 0 <= hour < 7:
        return "asian"
    return "off"


def make_setup_id(ts: str, timeframe: str, direction: str, setup_type: str, entry: float) -> str:
    raw = f"{ts}|{timeframe}|{direction}|{setup_type}|{round(entry, 2)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compute_excursions(
    df: pd.DataFrame,
    entry_index: int,
    direction: int,
    entry: float,
    sl: float,
    holding_bars: int,
) -> tuple[float, float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0, 0.0
    mfe = 0.0
    mae = 0.0
    end = min(len(df), entry_index + 1 + holding_bars)
    for j in range(entry_index + 1, end):
        hi = float(df.iloc[j]["high"])
        lo = float(df.iloc[j]["low"])
        if direction > 0:
            mfe = max(mfe, (hi - entry) / risk)
            mae = max(mae, (entry - lo) / risk)
        else:
            mfe = max(mfe, (entry - lo) / risk)
            mae = max(mae, (hi - entry) / risk)
    return round(mfe, 4), round(mae, 4)


def extract_setups_from_frame(
    df: pd.DataFrame,
    *,
    source_window_days: int,
    existing_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.filter_policy import aligned_session_hours, strategy_uses_kill_zone
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.domain.session_logic import is_kill_zone
    from tradingbot.domain.market_filters import compute_adx, atr_percentile as _atr_percentile
    from tradingbot.ml.feature_store import classify_regime

    cfg = get_price_action_config(SYMBOL, "M5")
    s0, s1 = aligned_session_hours(cfg)
    use_kz = strategy_uses_kill_zone(cfg)

    setups: list[dict[str, Any]] = []
    start = max(WARMUP, 60)
    n_bars = len(df)
    emit(f"  scan M5 @{source_window_days}d | bars={n_bars} start={start} tail={TAIL_BARS}")

    for i in range(start, n_bars):
        if i > start and (i - start) % 5000 == 0:
            emit(
                f"    progress M5 @{source_window_days}d bar {i}/{n_bars} setups={len(setups)}"
            )

        ts = df.index[i]
        ts_py = pd.Timestamp(ts).to_pydatetime()
        hour = ts_py.hour

        in_session = s0 <= hour < s1
        if not in_session:
            continue
        if use_kz and not is_kill_zone(ts_py, use_kill_zones=True):
            continue

        tail_start = max(0, i - TAIL_BARS)
        window = df.iloc[tail_start : i + 1]
        wi = len(window) - 1
        enriched = enrich_price_action(window, cfg, at_index=wi)
        setup = evaluate_gold_setup(enriched, wi, cfg, timeframe=EVAL_TF)
        if setup is None:
            continue

        entry = float(setup.entry)
        sl = float(setup.stop_loss)
        tp = float(setup.take_profit)
        if sl <= 0 or tp <= 0 or abs(entry - sl) <= 0:
            continue

        direction_str = "BUY" if setup.direction > 0 else "SELL"
        ts_str = str(ts)
        setup_type = setup.setup.value
        sid = make_setup_id(ts_str, "M5", direction_str, setup_type, entry)
        if existing_ids is not None and sid in existing_ids:
            continue

        risk = abs(entry - sl)
        rr_target = abs(tp - entry) / risk if risk > 0 else 0.0

        atr_window = df.iloc[max(0, i - 250) : i + 1]
        atr_pct = _atr_percentile(atr_window)
        if not np.isfinite(atr_pct):
            atr_pct = 50.0
        adx = compute_adx(df.iloc[: i + 1])
        regime = classify_regime(adx, atr_pct)

        setups.append({
            "setup_id": sid,
            "timestamp_utc": ts_str,
            "timeframe": "M5",
            "direction": direction_str,
            "entry_price": entry,
            "stop_price": sl,
            "tp_price": tp,
            "rr_target": round(rr_target, 4),
            "confidence": round(float(setup.confidence), 4),
            "confluence_score": round(float(setup.confluence), 4),
            "regime": regime,
            "atr_pct": round(float(atr_pct), 4),
            "spread_pips": 4.0,
            "session_name": session_name_from_hour(hour),
            "h1_bias": 0.0,
            "setup_type": setup_type,
            "raw_metadata_json": json.dumps(setup.metadata or {}, default=str),
            "bar_index": i,
            "preset": str(cfg.get("PRESET", "gold_ny_sweep")),
            "source_window_days": source_window_days,
        })

    emit(f"    -> {len(setups)} new raw setups from @{source_window_days}d")
    return setups


RAW_COLS = [
    "setup_id", "timestamp_utc", "timeframe", "direction", "entry_price", "stop_price",
    "tp_price", "rr_target", "confidence", "confluence_score", "regime", "atr_pct",
    "spread_pips", "session_name", "h1_bias", "setup_type", "raw_metadata_json",
    "bar_index", "preset", "source_window_days",
]


def seed_from_phase12a() -> pd.DataFrame:
    path = PHASE12A_LABELED if PHASE12A_LABELED.is_file() else PHASE12A_RAW
    if not path.is_file():
        emit("  no phase12a seed available")
        return pd.DataFrame(columns=RAW_COLS)
    df = pd.read_parquet(path)
    df = df[df["timeframe"] == "M5"].copy()
    for c in RAW_COLS:
        if c not in df.columns:
            df[c] = None if c != "source_window_days" else 90
    out = df[RAW_COLS].copy()
    out = out.drop_duplicates(subset=["setup_id"], keep="first")
    emit(f"  seeded M5 rows from {path.name}: {len(out)}")
    return out


def task1_extract() -> tuple[pd.DataFrame, dict[str, int]]:
    emit("TASK 1 - Full PA Setup Extraction (M5 only, hybrid seed + 180d)")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    seed = seed_from_phase12a()
    by_id: dict[str, dict[str, Any]] = {}
    window_counts = {30: 0, 60: 0, 90: 0, 180: 0}

    for _, r in seed.iterrows():
        d = r.to_dict()
        by_id[str(d["setup_id"])] = d
        w = int(d.get("source_window_days") or 0)
        if w in window_counts:
            window_counts[w] += 1

    if len(by_id) < 800:
        emit("  seed < 800; scanning 30/60/90 for additional unique setups")
        for days in (30, 60, 90):
            path = CACHE_DIR / f"XAUUSD_M5_{days}d.parquet"
            if not path.is_file():
                continue
            m5 = load_m5_parquet(days)
            rows = extract_setups_from_frame(
                m5, source_window_days=days, existing_ids=set(by_id.keys())
            )
            for row in rows:
                by_id[row["setup_id"]] = row
                window_counts[days] += 1
            emit(f"  cumulative unique after @{days}d: {len(by_id)}")

    path180 = CACHE_DIR / "XAUUSD_M5_180d.parquet"
    if path180.is_file():
        m5_180 = load_m5_parquet(180)
        rows180 = extract_setups_from_frame(
            m5_180, source_window_days=180, existing_ids=set(by_id.keys())
        )
        for row in rows180:
            by_id[row["setup_id"]] = row
            window_counts[180] += 1
        emit(f"  cumulative unique after @180d: {len(by_id)}")
    else:
        emit("  WARN: 180d cache missing; skip expansion scan")

    raw_df = pd.DataFrame(list(by_id.values()))
    if not raw_df.empty:
        raw_df = raw_df.drop_duplicates(subset=["setup_id"], keep="first")
        window_counts = {
            d: int((raw_df["source_window_days"] == d).sum()) for d in (30, 60, 90, 180)
        }

    out_path = DATA_DIR / "raw_pa_setups.parquet"
    raw_df.to_parquet(out_path, index=False)
    tgt = "YES" if len(raw_df) > 1200 else "NO"
    emit(f"Saved raw: {out_path} rows={len(raw_df)} (target >1200: {tgt})")
    for d in (30, 60, 90, 180):
        emit(f"  source_window_days={d}: {window_counts.get(d, 0)}")
    return raw_df, window_counts


def label_one(
    df: pd.DataFrame,
    entry_index: int,
    direction: int,
    entry: float,
    sl: float,
    tp: float,
    holding_bars: int,
) -> dict[str, Any]:
    from tradingbot.ml.dataset.schema import Label
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp

    if sl <= 0 or tp <= 0 or abs(entry - sl) <= 0:
        return {
            "label": -1,
            "tp_hit": False,
            "sl_hit": False,
            "timeout": True,
            "exit_reason": "invalid_levels",
            "mfe_r": 0.0,
            "mae_r": 0.0,
            "hold_bars": None,
            "bars_to_outcome": None,
            "realized_r_multiple": 0.0,
            "holding_window_bars": holding_bars,
        }

    outcome = resolve_label_with_sl_tp(
        df,
        entry_index,
        direction,
        sl,
        tp,
        future_window_bars=holding_bars,
        entry_price=entry,
    )
    lbl = int(outcome.get("label", Label.NO_RESOLUTION))
    exit_reason = str(outcome.get("exit_reason", "timeout"))
    tp_hit = bool(outcome.get("tp_hit", False))
    sl_hit = bool(outcome.get("sl_hit", False))
    timeout = exit_reason in ("timeout", "no_data", "invalid_levels") or lbl == int(Label.NO_RESOLUTION)

    if timeout and lbl != int(Label.NO_RESOLUTION):
        lbl = int(Label.NO_RESOLUTION)

    risk = abs(entry - sl)
    rr = abs(tp - entry) / risk if risk > 0 else 0.0
    if exit_reason == "tp":
        realized_r = rr
    elif exit_reason == "sl":
        realized_r = -1.0
    else:
        realized_r = 0.0

    mfe, mae = compute_excursions(df, entry_index, direction, entry, sl, holding_bars)
    bars = outcome.get("bars")

    return {
        "label": lbl,
        "tp_hit": tp_hit,
        "sl_hit": sl_hit,
        "timeout": bool(timeout),
        "exit_reason": exit_reason,
        "mfe_r": mfe,
        "mae_r": mae,
        "max_favorable_excursion_r": mfe,
        "max_adverse_excursion_r": mae,
        "hold_bars": bars,
        "bars_to_outcome": bars,
        "realized_r_multiple": round(realized_r, 4),
        "holding_window_bars": holding_bars,
    }


def task2_label(raw_df: pd.DataFrame) -> pd.DataFrame:
    emit("TASK 2 - Robust Outcome Labeling (holding_bars=48, timeouts stay -1)")
    if raw_df.empty:
        return raw_df

    frame_cache: dict[int, pd.DataFrame] = {}
    needed_days = sorted(set(int(x) for x in raw_df["source_window_days"].dropna().unique()))
    for days in needed_days:
        path = CACHE_DIR / f"XAUUSD_M5_{days}d.parquet"
        if path.is_file():
            frame_cache[days] = load_m5_parquet(days)
            emit(f"  cached frame @{days}d bars={len(frame_cache[days])}")

    labeled_rows: list[dict[str, Any]] = []
    n = len(raw_df)
    for k, (_, row) in enumerate(raw_df.iterrows(), start=1):
        if k % 200 == 0:
            emit(f"  label progress {k}/{n}")
        days = int(row["source_window_days"])
        df = frame_cache.get(days)
        if df is None:
            continue
        i = int(row["bar_index"])
        if i < 0 or i >= len(df):
            continue
        direction = 1 if row["direction"] == "BUY" else -1
        info = label_one(
            df,
            i,
            direction,
            float(row["entry_price"]),
            float(row["stop_price"]),
            float(row["tp_price"]),
            HOLDING_BARS_M5,
        )
        labeled_rows.append({**row.to_dict(), **info})

    labeled_df = pd.DataFrame(labeled_rows)
    out_path = DATA_DIR / "pa_setups_labeled_outcomes.parquet"
    labeled_df.to_parquet(out_path, index=False)
    emit(f"Saved labeled: {out_path} rows={len(labeled_df)}")
    if not labeled_df.empty:
        emit(f"  label counts: {labeled_df['label'].value_counts().to_dict()}")
        emit(f"  timeout flag True: {int(labeled_df['timeout'].sum())}")
        emit(f"  exit_reason: {labeled_df['exit_reason'].value_counts().to_dict()}")
    return labeled_df


def task3_features(labeled_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    emit("TASK 3 - Institutional 25-feature dataset")
    from tradingbot.ml.feature_store import FEATURES, InstitutionalFeatureStore, REGIME_LABEL_MAP
    from tradingbot.domain.market_filters import compute_adx

    if labeled_df.empty:
        return labeled_df, {}, {"error": "empty"}

    frame_cache: dict[int, pd.DataFrame] = {}
    needed_days = sorted(set(int(x) for x in labeled_df["source_window_days"].dropna().unique()))
    for days in needed_days:
        path = CACHE_DIR / f"XAUUSD_M5_{days}d.parquet"
        if path.is_file():
            frame_cache[days] = ensure_utc_index(load_m5_parquet(days))

    h4_src_days = max(frame_cache.keys()) if frame_cache else 90
    h4_ctx = ensure_utc_index(resample_h4(frame_cache[h4_src_days]))

    feature_rows: list[dict[str, Any]] = []
    n = len(labeled_df)
    for k, (_, row) in enumerate(labeled_df.iterrows(), start=1):
        if k % 200 == 0:
            emit(f"  feature progress {k}/{n}")
        days = int(row["source_window_days"])
        df = frame_cache.get(days)
        if df is None:
            continue
        i = int(row["bar_index"])
        if i < 0 or i >= len(df):
            continue

        feats = InstitutionalFeatureStore.compute_at(
            df, i, symbol=SYMBOL, h4_df=h4_ctx, regime=None
        )
        merged = {**row.to_dict()}
        for f in FEATURES:
            merged[f] = feats.get(f)

        adx_i = compute_adx(df.iloc[: i + 1])
        atr_pct = float(feats.get("atr_pct", merged.get("atr_pct", 50.0)) or 50.0)
        regime = InstitutionalFeatureStore.classify_regime(adx_i, atr_pct)
        merged["regime"] = regime
        merged["regime_code"] = REGIME_LABEL_MAP.get(regime, 0.0)
        merged["atr_pct"] = atr_pct
        feature_rows.append(merged)

    feat_df = pd.DataFrame(feature_rows)
    full_path = DATA_DIR / "pa_setups_featured.parquet"
    feat_df.to_parquet(full_path, index=False)
    emit(f"Saved featured: {full_path} rows={len(feat_df)}")

    FEATURE_COLS_ALL = list(FEATURES)
    binary = feat_df[feat_df["label"].isin([0, 1])].copy()
    for col in FEATURE_COLS_ALL:
        if col not in binary.columns:
            binary[col] = np.nan
    binary = binary[binary[FEATURE_COLS_ALL].notna().all(axis=1)].copy()
    binary["timestamp_utc"] = pd.to_datetime(binary["timestamp_utc"], utc=True, format="mixed")
    binary = binary.sort_values("timestamp_utc").reset_index(drop=True)

    regime_dfs: dict[str, pd.DataFrame] = {}
    counts: dict[str, int] = {}
    for regime in REGIMES:
        sub = binary[binary["regime"] == regime].copy()
        path = DATA_DIR / f"dataset_{regime.lower()}.parquet"
        sub.to_parquet(path, index=False)
        regime_dfs[regime] = sub
        counts[regime] = len(sub)
        meet = "YES" if len(sub) >= 300 else "NO"
        emit(f"  {regime}: {len(sub)} (target>=300: {meet}) -> {path.name}")

    timeout_n = int((feat_df["label"] == -1).sum()) if "label" in feat_df.columns else 0
    summary = {
        "featured_rows": len(feat_df),
        "binary_total": int(len(binary)),
        "timeout_count": timeout_n,
        "regime_binary_counts": counts,
        "target_per_regime": 300,
        "target_total_binary": 900,
        "meets_total": int(len(binary)) >= 900,
        "feature_cols": FEATURE_COLS_ALL,
    }
    meet900 = "YES" if len(binary) >= 900 else "NO"
    emit(f"  binary labeled total={len(binary)} (target>=900: {meet900})")
    emit(f"  timeout rows kept as -1 (not converted): {timeout_n}")
    return feat_df, regime_dfs, summary


def _brier(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((y_prob - y_true) ** 2))


def _calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    if n == 0:
        return 1.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        acc = float(y_true[mask].mean())
        conf = float(y_prob[mask].mean())
        ece += (cnt / n) * abs(conf - acc)
    return round(float(ece), 4)


def _apply_calibration(
    method: str, train_prob: np.ndarray, y_train: np.ndarray, test_prob: np.ndarray
) -> tuple[np.ndarray, Any]:
    train_prob = np.clip(train_prob, 1e-6, 1 - 1e-6)
    test_prob = np.clip(test_prob, 1e-6, 1 - 1e-6)
    if method == "platt":
        from sklearn.linear_model import LogisticRegression

        lr = LogisticRegression(max_iter=500)
        lr.fit(train_prob.reshape(-1, 1), y_train)
        return lr.predict_proba(test_prob.reshape(-1, 1))[:, 1], lr
    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression

        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(train_prob, y_train)
        return iso.predict(test_prob), iso
    return test_prob, None


def _trade_metrics(rs: list[float]) -> dict[str, float]:
    if not rs:
        return {"pf": 0.0, "expectancy_r": 0.0, "max_dd_r": 0.0, "trades": 0, "win_rate": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "pf": round(min(pf, 999.0), 4),
        "expectancy_r": round(sum(rs) / len(rs), 4),
        "max_dd_r": round(mdd, 4),
        "trades": len(rs),
        "win_rate": round(len(wins) / len(rs), 4),
    }


def _precision_side(y_true, y_prob, directions, side: str, th: float) -> float:
    mask = (directions == side) & (y_prob >= th)
    if mask.sum() == 0:
        return 0.0
    return float(y_true[mask].mean())


def psi_histogram(expected: np.ndarray, actual: np.ndarray, n_bins: int = PSI_BINS) -> float:
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 5 or len(actual) < 5:
        return 0.0
    qs = np.linspace(0, 100, n_bins + 1)
    breaks = np.unique(np.percentile(expected, qs))
    if len(breaks) < 3:
        return 0.0
    e_counts = np.histogram(expected, bins=breaks)[0].astype(float)
    a_counts = np.histogram(actual, bins=breaks)[0].astype(float)
    e_pct = (e_counts + 1e-6) / (e_counts.sum() + 1e-6 * len(e_counts))
    a_pct = (a_counts + 1e-6) / (a_counts.sum() + 1e-6 * len(a_counts))
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def mean_feature_psi(df: pd.DataFrame, feature_cols: list[str]) -> float:
    if len(df) < 20:
        return 0.0
    ordered = df.copy()
    ordered["timestamp_utc"] = pd.to_datetime(ordered["timestamp_utc"], utc=True, format="mixed")
    ordered = ordered.sort_values("timestamp_utc").reset_index(drop=True)
    cut = int(len(ordered) * 0.70)
    early = ordered.iloc[:cut]
    late = ordered.iloc[cut:]
    vals = []
    for c in feature_cols:
        if c not in ordered.columns:
            continue
        vals.append(psi_histogram(early[c].astype(float).values, late[c].astype(float).values))
    return float(np.mean(vals)) if vals else 0.0


def _make_model(model_type: str, y_train: np.ndarray):
    pos = max(int((y_train == 1).sum()), 1)
    neg = max(int((y_train == 0).sum()), 1)
    spw = neg / pos

    if model_type == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=140,
            max_depth=5,
            learning_rate=0.05,
            random_state=42,
            verbose=-1,
            is_unbalance=True,
        )
    if model_type == "xgboost":
        import xgboost as xgb

        return xgb.XGBClassifier(
            n_estimators=140,
            max_depth=5,
            learning_rate=0.05,
            random_state=42,
            eval_metric="logloss",
            verbosity=0,
            scale_pos_weight=spw,
        )
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(
        n_estimators=250,
        max_depth=6,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )


def train_regime(regime: str, df: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
    from sklearn.model_selection import TimeSeriesSplit

    emit(f"  train {regime} samples={len(df)}")
    if len(df) < 40:
        return {
            "skipped": True,
            "samples": len(df),
            "reason": "insufficient_samples",
            "models": [],
            "best": None,
        }

    X = df[feature_cols].astype(float).values
    y = df["label"].astype(int).values
    directions = df["direction"].astype(str).values
    rs = df["realized_r_multiple"].astype(float).values
    ts = pd.to_datetime(df["timestamp_utc"], utc=True, format="mixed")

    tscv = TimeSeriesSplit(n_splits=5)
    model_types = ["lightgbm", "xgboost", "random_forest"]
    results: list[dict[str, Any]] = []
    regime_best: dict[str, Any] | None = None
    regime_best_rank = (-1.0, -1.0, 999.0)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for model_type in model_types:
        try:
            _ = _make_model(model_type, y)
        except Exception as exc:
            emit(f"    skip {model_type}: {exc}")
            continue

        fold_rows: list[dict[str, Any]] = []
        all_cal_prob: list[float] = []
        all_y: list[int] = []
        all_dirs: list[str] = []
        all_rs: list[float] = []
        cal_votes: list[str] = []

        for fold_i, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            if len(np.unique(y_tr)) < 2:
                continue

            model = _make_model(model_type, y_tr)
            model.fit(X_tr, y_tr)
            tr_prob = model.predict_proba(X_tr)[:, 1]
            te_prob = model.predict_proba(X_te)[:, 1]

            cal_scores = {}
            cal_probs = {}
            for m in ("platt", "isotonic"):
                p, _cal = _apply_calibration(m, tr_prob, y_tr, te_prob)
                cal_probs[m] = p
                cal_scores[m] = _brier(y_te, p)
            best_cal = min(cal_scores, key=cal_scores.get)
            cal_prob = cal_probs[best_cal]
            cal_votes.append(best_cal)

            taken = [float(r) for p, r in zip(cal_prob, rs[test_idx]) if p >= DECISION_THRESHOLD]
            tm = _trade_metrics(taken)
            ece = _calibration_error(y_te, cal_prob)

            fold_rows.append({
                "fold": fold_i,
                "precision_buy": round(
                    _precision_side(y_te, cal_prob, directions[test_idx], "BUY", DECISION_THRESHOLD), 4
                ),
                "precision_sell": round(
                    _precision_side(y_te, cal_prob, directions[test_idx], "SELL", DECISION_THRESHOLD), 4
                ),
                "brier_score": round(cal_scores[best_cal], 4),
                "calibration_error": ece,
                "calibration_method": best_cal,
                "oos_pf": tm["pf"],
                "oos_expectancy_r": tm["expectancy_r"],
                "max_dd_r": tm["max_dd_r"],
                "oos_trades": tm["trades"],
            })
            all_cal_prob.extend(cal_prob.tolist())
            all_y.extend(y_te.tolist())
            all_dirs.extend(directions[test_idx].tolist())
            all_rs.extend(rs[test_idx].tolist())

        if not fold_rows:
            continue

        all_cal_arr = np.asarray(all_cal_prob, dtype=float)
        all_y_arr = np.asarray(all_y, dtype=int)
        all_dirs_arr = np.asarray(all_dirs, dtype=str)
        taken_all = [float(r) for p, r in zip(all_cal_arr, all_rs) if p >= DECISION_THRESHOLD]
        tm_all = _trade_metrics(taken_all)
        best_cal_method = Counter(cal_votes).most_common(1)[0][0] if cal_votes else "platt"

        metrics = {
            "precision_buy": round(
                _precision_side(all_y_arr, all_cal_arr, all_dirs_arr, "BUY", DECISION_THRESHOLD), 4
            ),
            "precision_sell": round(
                _precision_side(all_y_arr, all_cal_arr, all_dirs_arr, "SELL", DECISION_THRESHOLD), 4
            ),
            "brier_score": round(_brier(all_y_arr, all_cal_arr), 4),
            "calibration_error": _calibration_error(all_y_arr, all_cal_arr),
            "calibration_method": best_cal_method,
            "oos_pf": tm_all["pf"],
            "oos_expectancy_r": tm_all["expectancy_r"],
            "max_dd_r": tm_all["max_dd_r"],
            "oos_trades": tm_all["trades"],
            "fold_avg_pf": round(float(np.mean([f["oos_pf"] for f in fold_rows])), 4),
            "fold_avg_brier": round(float(np.mean([f["brier_score"] for f in fold_rows])), 4),
        }

        full = _make_model(model_type, y)
        full.fit(X, y)
        full_prob = full.predict_proba(X)[:, 1]
        _, calibrator = _apply_calibration(best_cal_method, full_prob, y, full_prob)

        artifact = {
            "model": full,
            "features": feature_cols,
            "regime": regime,
            "model_type": model_type,
            "metrics": metrics,
            "calibration_method": best_cal_method,
            "calibrator": calibrator,
            "decision_threshold": DECISION_THRESHOLD,
            "train_period": f"{ts.iloc[0]} -> {ts.iloc[int(len(ts) * 0.8)]}",
            "validation_period": f"{ts.iloc[int(len(ts) * 0.8)]} -> {ts.iloc[-1]}",
        }
        artifact_path = MODEL_DIR / f"{regime.lower()}_{model_type}.pkl"
        try:
            artifact_path.write_bytes(pickle.dumps(artifact))
        except Exception:
            artifact["calibrator"] = None
            artifact_path.write_bytes(pickle.dumps(artifact))

        entry = {
            "regime": regime,
            "model_type": model_type,
            "samples": len(df),
            "metrics": metrics,
            "artifact": str(artifact_path.relative_to(ROOT)).replace("\\", "/"),
            "folds": fold_rows,
        }
        results.append(entry)
        emit(
            f"    {model_type}: PF={metrics['oos_pf']} expR={metrics['oos_expectancy_r']} "
            f"brier={metrics['brier_score']} cal={best_cal_method} ece={metrics['calibration_error']}"
        )

        rank = (min(metrics["oos_pf"], 10.0), metrics["oos_expectancy_r"], -metrics["brier_score"])
        if rank > regime_best_rank:
            regime_best_rank = rank
            regime_best = entry

    return {
        "regime": regime,
        "samples": len(df),
        "models": results,
        "best": regime_best,
    }


def task4_train(regime_dfs: dict[str, pd.DataFrame], feature_cols: list[str]) -> dict[str, Any]:
    emit("TASK 4 - Retrain regime models (LGBM/XGB/RF + Platt/Isotonic)")
    training: dict[str, Any] = {
        "regimes": {},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_threshold": DECISION_THRESHOLD,
    }
    for regime in REGIMES:
        training["regimes"][regime] = train_regime(
            regime, regime_dfs.get(regime, pd.DataFrame()), feature_cols
        )
    return training


def task5_certify(
    training: dict[str, Any],
    regime_dfs: dict[str, pd.DataFrame],
    feature_cols: list[str],
) -> dict[str, Any]:
    emit("TASK 5 - Institutional Certification")
    cert: dict[str, Any] = {"regimes": {}, "certified_regimes": []}

    for regime in REGIMES:
        info = training["regimes"].get(regime, {})
        best = info.get("best") or {}
        m = best.get("metrics") or {}
        df = regime_dfs.get(regime, pd.DataFrame())
        samples = int(len(df))
        psi = mean_feature_psi(df, feature_cols) if samples else 0.0

        checks = {
            "samples_gte_300": samples >= GATE["samples"],
            "oos_pf_gte_125": float(m.get("oos_pf", 0)) >= GATE["oos_pf"],
            "oos_exp_gte_015": float(m.get("oos_expectancy_r", 0)) >= GATE["oos_expectancy_r"],
            "precision_buy_gte_58": float(m.get("precision_buy", 0)) >= GATE["precision_buy"],
            "precision_sell_gte_58": float(m.get("precision_sell", 0)) >= GATE["precision_sell"],
            "brier_lt_012": float(m.get("brier_score", 1)) < GATE["brier_score"],
            "psi_lt_025": psi < GATE["psi"],
        }
        passed = all(checks.values()) and bool(best)
        cert["regimes"][regime] = {
            "best_model": best.get("model_type"),
            "samples": samples,
            "metrics": m,
            "psi": round(psi, 6),
            "ece": m.get("calibration_error"),
            "checks": checks,
            "certified": passed,
        }
        emit(
            f"  {regime}: certified={passed} model={best.get('model_type')} "
            f"PF={m.get('oos_pf')} exp={m.get('oos_expectancy_r')} psi={psi:.4f}"
        )
        if passed:
            cert["certified_regimes"].append(regime)

    cert["certified_count"] = len(cert["certified_regimes"])
    return cert


def write_report(
    window_counts: dict[str, int],
    raw_n: int,
    labeled_df: pd.DataFrame,
    feat_summary: dict[str, Any],
    training: dict[str, Any],
    cert: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("PHASE 13D - ML Data Expansion & Retraining Report")
    lines.append(f"Generated UTC: {datetime.now(timezone.utc).isoformat()}")
    lines.append("Mode: RESEARCH/TRAINING ONLY | USE_ML_KERNEL=false | DRY_RUN=1")
    lines.append("")

    lines.append("1. RAW SETUP COUNTS")
    lines.append(f"  total_unique_raw={raw_n}")
    for d in (30, 60, 90, 180):
        lines.append(f"  window_{d}d={window_counts.get(d, 0)}")
    lines.append(f"  target_gt_1200={'YES' if raw_n > 1200 else 'NO'}")
    lines.append("")

    lines.append("2. LABELED DATASET SUMMARY")
    if labeled_df is None or labeled_df.empty:
        lines.append("  empty")
        timeout_n = 0
        labeled_any = 0
    else:
        labeled_any = len(labeled_df)
        vc = labeled_df["label"].value_counts().to_dict()
        timeout_n = int(labeled_df["timeout"].sum()) if "timeout" in labeled_df.columns else int(vc.get(-1, 0))
        lines.append(f"  rows_with_outcome_label={labeled_any}")
        lines.append(f"  label_1_tp={vc.get(1, 0)}")
        lines.append(f"  label_0_sl={vc.get(0, 0)}")
        lines.append(f"  label_-1_timeout={vc.get(-1, 0)}")
        lines.append(f"  timeout_flag_count={timeout_n}")
        lines.append("  note: timeouts NEVER converted to losses")
        if "exit_reason" in labeled_df.columns:
            lines.append(f"  exit_reason={labeled_df['exit_reason'].value_counts().to_dict()}")
    lines.append("")

    lines.append("3. REGIME SAMPLE COUNTS (binary labeled)")
    rc = feat_summary.get("regime_binary_counts", {})
    binary_total = int(feat_summary.get("binary_total", 0))
    for regime in REGIMES:
        n = int(rc.get(regime, 0))
        lines.append(f"  {regime}={n} meet_300={'YES' if n >= 300 else 'NO'}")
    lines.append(f"  BINARY_TOTAL={binary_total} meet_900={'YES' if binary_total >= 900 else 'NO'}")
    lines.append(f"  featured_rows_incl_timeout={feat_summary.get('featured_rows', 0)}")
    lines.append(f"  timeout_in_featured={feat_summary.get('timeout_count', 0)}")
    lines.append("")

    lines.append("4. MODEL TRAINING MATRIX")
    for regime in REGIMES:
        info = training["regimes"].get(regime, {})
        lines.append(f"  [{regime}] samples={info.get('samples', 0)}")
        for entry in info.get("models") or []:
            m = entry.get("metrics") or {}
            lines.append(
                f"    {entry.get('model_type')}: PF={m.get('oos_pf')} expR={m.get('oos_expectancy_r')} "
                f"Pbuy={m.get('precision_buy')} Psell={m.get('precision_sell')} "
                f"brier={m.get('brier_score')} ece={m.get('calibration_error')} trades={m.get('oos_trades')}"
            )
        best = info.get("best") or {}
        lines.append(f"    BEST={best.get('model_type', 'NONE')}")
    lines.append("")

    lines.append("5. CALIBRATION RESULTS")
    for regime in REGIMES:
        info = training["regimes"].get(regime, {})
        for entry in info.get("models") or []:
            m = entry.get("metrics") or {}
            lines.append(
                f"  {regime}/{entry.get('model_type')}: method={m.get('calibration_method')} "
                f"brier={m.get('brier_score')} ece={m.get('calibration_error')}"
            )
    lines.append("")

    lines.append("6. CERTIFICATION GATES")
    lines.append("  gates: samples>=300, OOS_PF>=1.25, exp>=+0.15R, Pbuy>=0.58, Psell>=0.58, Brier<0.12, PSI<0.25")
    for regime in REGIMES:
        c = cert["regimes"].get(regime, {})
        lines.append(
            f"  {regime}: certified={c.get('certified')} model={c.get('best_model')} "
            f"psi={c.get('psi')} checks={c.get('checks')}"
        )
    lines.append(f"  CERTIFIED_REGIMES={cert.get('certified_regimes')}")
    lines.append("")

    best_regime = "NONE"
    best_pf = -1.0
    best_exp = 0.0
    best_brier = 1.0
    for regime in REGIMES:
        info = training["regimes"].get(regime, {})
        best = info.get("best") or {}
        m = best.get("metrics") or {}
        pf = float(m.get("oos_pf", -1) or -1)
        if pf > best_pf:
            best_pf = pf
            best_regime = regime if best else "NONE"
            best_exp = float(m.get("oos_expectancy_r", 0) or 0)
            best_brier = float(m.get("brier_score", 1) or 1)

    certified_n = int(cert.get("certified_count", 0))
    inst_ready = "YES" if (certified_n >= 1 and binary_total >= 900) else "NO"
    keep_shadow = "YES" if inst_ready == "NO" else "NO"

    lines.append("7. SHADOW-ONLY OR LIVE-ELIGIBLE VERDICT")
    lines.append(f"  ML_KERNEL_INSTITUTIONAL_READY={inst_ready}")
    lines.append(f"  KEEP_SHADOW_MODE={keep_shadow}")
    lines.append("  note: no live ML enable / no router changes / no orders in this phase")
    lines.append("")

    lines.append("PHASE_13D_RESULT")
    lines.append(f"RAW_SETUPS={raw_n}")
    lines.append(f"LABELED_SAMPLES={binary_total}")
    lines.append(f"TREND_SAMPLES={int(rc.get('TREND', 0))}")
    lines.append(f"EXPANSION_SAMPLES={int(rc.get('EXPANSION', 0))}")
    lines.append(f"RANGING_SAMPLES={int(rc.get('RANGING', 0))}")
    lines.append(f"CERTIFIED_MODELS={certified_n}")
    lines.append(f"BEST_REGIME={best_regime}")
    lines.append(f"BEST_OOS_PF={best_pf if best_pf >= 0 else 0.0}")
    lines.append(f"BEST_EXPECTANCY_R={best_exp}")
    lines.append(f"BEST_BRIER={best_brier}")
    lines.append(f"ML_KERNEL_INSTITUTIONAL_READY={inst_ready}")
    lines.append(f"KEEP_SHADOW_MODE={keep_shadow}")

    text = "\n".join(lines) + "\n"
    REPORT_PATH.write_bytes(text.encode("utf-8"))
    emit(f"Report -> {REPORT_PATH}")
    return text



def maybe_resume_from_disk() -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any], dict[str, int], pd.DataFrame] | None:
    """Resume after TASK3 if artifacts already exist (skip slow PA/feature rebuild)."""
    featured_path = DATA_DIR / "pa_setups_featured.parquet"
    labeled_path = DATA_DIR / "pa_setups_labeled_outcomes.parquet"
    raw_path = DATA_DIR / "raw_pa_setups.parquet"
    if not featured_path.is_file():
        return None
    emit("RESUME - loading existing phase13d featured/regime datasets")
    feat_df = pd.read_parquet(featured_path)
    labeled_df = pd.read_parquet(labeled_path) if labeled_path.is_file() else feat_df
    raw_df = pd.read_parquet(raw_path) if raw_path.is_file() else feat_df
    from tradingbot.ml.feature_store import FEATURES
    feature_cols = list(FEATURES)
    binary = feat_df[feat_df["label"].isin([0, 1])].copy()
    for col in feature_cols:
        if col not in binary.columns:
            binary[col] = np.nan
    binary = binary[binary[feature_cols].notna().all(axis=1)].copy()
    binary["timestamp_utc"] = pd.to_datetime(binary["timestamp_utc"], utc=True, format="mixed")
    binary = binary.sort_values("timestamp_utc").reset_index(drop=True)
    regime_dfs: dict[str, pd.DataFrame] = {}
    counts: dict[str, int] = {}
    for regime in REGIMES:
        path = DATA_DIR / f"dataset_{regime.lower()}.parquet"
        if path.is_file():
            sub = pd.read_parquet(path)
        else:
            sub = binary[binary["regime"] == regime].copy()
            sub.to_parquet(path, index=False)
        regime_dfs[regime] = sub
        counts[regime] = len(sub)
        emit(f"  resume {regime}: {len(sub)}")
    window_counts = {d: int((raw_df["source_window_days"] == d).sum()) for d in (30, 60, 90, 180)} if "source_window_days" in raw_df.columns else {30:0,60:0,90:0,180:0}
    summary = {
        "featured_rows": len(feat_df),
        "binary_total": int(len(binary)),
        "timeout_count": int((feat_df["label"] == -1).sum()) if "label" in feat_df.columns else 0,
        "regime_binary_counts": counts,
        "target_per_regime": 300,
        "target_total_binary": 900,
        "meets_total": int(len(binary)) >= 900,
        "feature_cols": feature_cols,
        "resumed": True,
    }
    return labeled_df, regime_dfs, summary, window_counts, raw_df


def main() -> int:
    from tradingbot.config.dotenv_loader import load_dotenv

    load_dotenv()
    os.environ["USE_ML_KERNEL"] = "false"
    os.environ["TRADINGBOT_DISABLE_JOURNAL"] = "1"
    os.environ["TRADINGBOT_SIGNAL_FILTER"] = "OFF"
    os.environ["TRADINGBOT_DRY_RUN"] = "1"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    emit(f"PHASE 13D ML Retraining | UTC {datetime.now(timezone.utc).isoformat()}")
    emit(f"USE_ML_KERNEL={os.environ.get('USE_ML_KERNEL')}")

    resumed = maybe_resume_from_disk() if os.environ.get("PHASE13D_FORCE_FULL", "0") != "1" else None
    if resumed is not None:
        labeled_df, regime_dfs, feat_summary, window_counts, raw_df = resumed
    else:
        raw_df, window_counts = task1_extract()
        labeled_df = task2_label(raw_df)
        feat_df, regime_dfs, feat_summary = task3_features(labeled_df)
    feature_cols = list(feat_summary.get("feature_cols") or [])
    if not feature_cols:
        from tradingbot.ml.feature_store import FEATURES

        feature_cols = list(FEATURES)

    training = task4_train(regime_dfs, feature_cols)
    cert = task5_certify(training, regime_dfs, feature_cols)

    matrix = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_threshold": DECISION_THRESHOLD,
        "gates": GATE,
        "window_counts": window_counts,
        "feature_summary": {k: v for k, v in feat_summary.items() if k != "feature_cols"},
        "feature_cols": feature_cols,
        "training": training,
        "certification": cert,
    }
    matrix_path = LOG_DIR / "training_matrix.json"
    matrix_path.write_bytes(json.dumps(matrix, indent=2, default=str).encode("utf-8"))
    emit(f"Matrix -> {matrix_path}")

    report_text = write_report(window_counts, len(raw_df), labeled_df, feat_summary, training, cert)
    if "PHASE_13D_RESULT" in report_text:
        emit("")
        emit(report_text[report_text.index("PHASE_13D_RESULT"):].rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
