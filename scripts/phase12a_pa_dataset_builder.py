#!/usr/bin/env python3
"""
PHASE 12A — Full PA Institutional Dataset Builder (READ-ONLY + BUILD).

Does NOT modify live trading flags or enable USE_ML_KERNEL.
Outputs: logs/phase12a/ and data/ml/research/phase12a/
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "phase12a"
DATA_DIR = ROOT / "data" / "ml" / "research" / "phase12a"
CACHE_DIR = ROOT / "data" / "cache"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
})
warnings.filterwarnings("ignore")

SYMBOL = "XAUUSD"
WINDOWS = (90, 60, 30)
TF_CONFIG = {
    "M5": {"preset": "gold_ny_sweep", "holding_bars": 48, "warmup": 500, "eval_tf": "5m"},
    "M15": {"preset": "atr_tight_gold", "holding_bars": 24, "warmup": 120, "eval_tf": "15m"},
    "H4": {"preset": "gold_h4_swing", "holding_bars": 12, "warmup": 60, "eval_tf": "4h"},
}
RESAMPLE_RULE = {"M5": None, "M15": "15min", "H4": "4h"}


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


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    rule = RESAMPLE_RULE[timeframe]
    if rule is None:
        return df
    agg = (
        df.resample(rule)
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


def label_setup(
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
            "bars_to_outcome": None,
            "realized_r_multiple": 0.0,
            "exit_reason": "invalid_levels",
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
    risk = abs(entry - sl)
    rr = abs(tp - entry) / risk if risk > 0 else 0.0

    if outcome.get("exit_reason") == "tp":
        realized_r = rr
    elif outcome.get("exit_reason") == "sl":
        realized_r = -1.0
    else:
        realized_r = 0.0

    return {
        "label": lbl,
        "bars_to_outcome": outcome.get("bars"),
        "realized_r_multiple": round(realized_r, 4),
        "exit_reason": outcome.get("exit_reason"),
    }


def extract_setups_from_frame(
    df: pd.DataFrame,
    timeframe: str,
    *,
    source_window_days: int,
) -> list[dict[str, Any]]:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.filter_policy import aligned_session_hours, strategy_uses_kill_zone
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.domain.session_logic import is_kill_zone
    from tradingbot.domain.market_filters import compute_adx
    from tradingbot.ml.feature_store import classify_regime

    cfg = get_price_action_config(SYMBOL, timeframe)
    tf_meta = TF_CONFIG[timeframe]
    eval_tf = tf_meta["eval_tf"]
    warmup = tf_meta["warmup"]
    s0, s1 = aligned_session_hours(cfg)
    use_kz = strategy_uses_kill_zone(cfg)

    setups: list[dict[str, Any]] = []
    start = max(warmup, 60)
    n_bars = len(df)
    emit(f"  scan {timeframe} @{source_window_days}d | bars={n_bars} start={start}")

    for i in range(start, n_bars):
        if i > start and (i - start) % 5000 == 0:
            emit(f"    progress {timeframe} @{source_window_days}d bar {i}/{n_bars} setups={len(setups)}")

        ts = df.index[i]
        ts_py = pd.Timestamp(ts).to_pydatetime()
        hour = ts_py.hour

        in_session = s0 <= hour < s1
        if not in_session:
            continue
        if use_kz and not is_kill_zone(ts_py, use_kill_zones=True):
            continue

        # Causal tail window — avoid O(n²) full-frame copy inside enrich_price_action.
        tail_start = max(0, i - 300)
        window = df.iloc[tail_start : i + 1]
        wi = len(window) - 1
        enriched = enrich_price_action(window, cfg, at_index=wi)
        setup = evaluate_gold_setup(enriched, wi, cfg, timeframe=eval_tf)
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
        risk = abs(entry - sl)
        rr_target = abs(tp - entry) / risk if risk > 0 else 0.0

        row = df.iloc[i]
        from tradingbot.domain.market_filters import atr_percentile as _atr_percentile

        atr_window = df.iloc[max(0, i - 250) : i + 1]
        atr_pct = _atr_percentile(atr_window)
        if not np.isfinite(atr_pct):
            atr_pct = 50.0
        adx = compute_adx(df.iloc[: i + 1])
        regime = classify_regime(adx, atr_pct)

        setups.append({
            "setup_id": make_setup_id(ts_str, timeframe, direction_str, setup_type, entry),
            "timestamp_utc": ts_str,
            "timeframe": timeframe,
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
            "preset": str(cfg.get("PRESET", tf_meta["preset"])),
            "source_window_days": source_window_days,
        })

    emit(f"    -> {len(setups)} raw setups")
    return setups


def _extract_worker(days: int, timeframe: str) -> list[dict[str, Any]]:
    """Process-pool worker: load cache + scan one (window, TF) cell."""
    os.environ.setdefault("USE_ML_KERNEL", "false")
    os.environ.setdefault("TRADINGBOT_DISABLE_JOURNAL", "1")
    os.environ.setdefault("TRADINGBOT_SIGNAL_FILTER", "OFF")
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    m5 = load_m5_parquet(days)
    df = m5 if timeframe == "M5" else resample_ohlcv(m5, timeframe)
    return extract_setups_from_frame(df, timeframe, source_window_days=days)


def task1_extract_all(*, parallel: bool = True) -> pd.DataFrame:
    emit("TASK 1 — Full Setup Extraction")
    all_rows: dict[str, dict[str, Any]] = {}
    checkpoint = DATA_DIR / "pa_setups_raw_checkpoint.parquet"
    if checkpoint.is_file():
        try:
            prev = pd.read_parquet(checkpoint)
            for _, r in prev.iterrows():
                all_rows[str(r["setup_id"])] = r.to_dict()
            emit(f"Resumed checkpoint: {len(all_rows)} setups")
        except Exception:
            pass

    jobs = [(days, tf) for days in WINDOWS for tf in ("M5", "M15", "H4")]

    def _merge(rows: list[dict[str, Any]], days: int, tf: str) -> None:
        for row in rows:
            all_rows[row["setup_id"]] = row
        emit(f"  merged {tf} @{days}d -> cumulative unique={len(all_rows)}")
        pd.DataFrame(list(all_rows.values())).to_parquet(checkpoint, index=False)

    if parallel:
        emit(f"Parallel extraction: {len(jobs)} jobs")
        with ProcessPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            futures = {
                pool.submit(_extract_worker, days, tf): (days, tf) for days, tf in jobs
            }
            for fut in as_completed(futures):
                days, tf = futures[fut]
                rows = fut.result()
                _merge(rows, days, tf)
    else:
        for days in WINDOWS:
            emit(f"Loading M5 {days}d cache ...")
            m5 = load_m5_parquet(days)
            frames = {"M5": m5, "M15": resample_ohlcv(m5, "M15"), "H4": resample_ohlcv(m5, "H4")}
            for tf in ("M5", "M15", "H4"):
                rows = extract_setups_from_frame(frames[tf], tf, source_window_days=days)
                _merge(rows, days, tf)

    raw_df = pd.DataFrame(list(all_rows.values()))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = DATA_DIR / "pa_setups_raw.parquet"
    raw_df.to_parquet(raw_path, index=False)
    if checkpoint.is_file():
        checkpoint.unlink(missing_ok=True)
    emit(f"Saved raw: {raw_path} rows={len(raw_df)}")
    return raw_df


def task2_label(raw_df: pd.DataFrame) -> pd.DataFrame:
    emit("TASK 2 — Forward Outcome Labeling")
    if raw_df.empty:
        return raw_df

    labeled_rows: list[dict[str, Any]] = []
    frame_cache: dict[tuple[int, str], pd.DataFrame] = {}
    h4_ref = load_m5_parquet(90)  # HTF context for feature store
    h4_ctx = resample_ohlcv(h4_ref, "H4")

    for days in WINDOWS:
        m5 = load_m5_parquet(days)
        frame_cache[(days, "M5")] = m5
        frame_cache[(days, "M15")] = resample_ohlcv(m5, "M15")
        frame_cache[(days, "H4")] = resample_ohlcv(m5, "H4")

    for _, row in raw_df.iterrows():
        tf = str(row["timeframe"])
        days = int(row["source_window_days"])
        df = frame_cache.get((days, tf))
        if df is None:
            continue
        i = int(row["bar_index"])
        if i >= len(df):
            continue

        direction = 1 if row["direction"] == "BUY" else -1
        holding = TF_CONFIG[tf]["holding_bars"]
        entry = float(row["entry_price"])
        sl = float(row["stop_price"])
        tp = float(row["tp_price"])

        label_info = label_setup(df, i, direction, entry, sl, tp, holding)
        mfe, mae = compute_excursions(df, i, direction, entry, sl, holding)

        labeled_rows.append({
            **row.to_dict(),
            **label_info,
            "max_favorable_excursion_r": mfe,
            "max_adverse_excursion_r": mae,
            "holding_window_bars": holding,
        })

    labeled_df = pd.DataFrame(labeled_rows)
    out_path = DATA_DIR / "pa_setups_labeled.parquet"
    labeled_df.to_parquet(out_path, index=False)
    emit(f"Saved labeled: {out_path} rows={len(labeled_df)}")
    return labeled_df


def ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV index to UTC tz-aware for feature-store HTF alignment."""
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def task3_features(labeled_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    emit("TASK 3 — Institutional Feature Expansion")
    from tradingbot.ml.feature_store import FEATURES, InstitutionalFeatureStore
    from tradingbot.domain.market_filters import compute_adx
    from tradingbot.domain.market_filters import compute_adx

    if labeled_df.empty:
        return labeled_df, {"error": "empty dataset"}

    frame_cache: dict[tuple[int, str], pd.DataFrame] = {}
    h4_ctx = ensure_utc_index(resample_ohlcv(load_m5_parquet(90), "H4"))
    for days in WINDOWS:
        m5 = ensure_utc_index(load_m5_parquet(days))
        frame_cache[(days, "M5")] = m5
        frame_cache[(days, "M15")] = ensure_utc_index(resample_ohlcv(m5, "M15"))
        frame_cache[(days, "H4")] = ensure_utc_index(resample_ohlcv(m5, "H4"))

    feature_rows: list[dict[str, Any]] = []
    missing_counts: dict[str, int] = {f: 0 for f in FEATURES}
    total = 0

    for n_done, (_, row) in enumerate(labeled_df.iterrows(), start=1):
        if n_done % 200 == 0:
            emit(f"  feature progress {n_done}/{len(labeled_df)}")
        tf = str(row["timeframe"])
        days = int(row["source_window_days"])
        df = frame_cache.get((days, tf))
        if df is None:
            continue
        i = int(row["bar_index"])
        if i >= len(df):
            continue

        feats = InstitutionalFeatureStore.compute_at(
            df, i, symbol=SYMBOL, h4_df=h4_ctx, regime=None
        )
        row["h1_bias"] = feats.get("h1_trend", 0.0)
        row["spread_pips"] = feats.get("spread_pips", 4.0)

        merged = {**row.to_dict()}
        for f in FEATURES:
            val = feats.get(f)
            merged[f] = val
            if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
                missing_counts[f] += 1
        # Refresh regime from institutional atr_pct + causal ADX (extraction may have used stale defaults).
        adx_i = compute_adx(df.iloc[: i + 1])
        merged["regime"] = InstitutionalFeatureStore.classify_regime(
            adx_i, float(feats.get("atr_pct", 50.0))
        )
        from tradingbot.ml.feature_store import REGIME_LABEL_MAP

        merged["regime_code"] = REGIME_LABEL_MAP.get(merged["regime"], 0.0)
        total += 1
        feature_rows.append(merged)

    feat_df = pd.DataFrame(feature_rows)
    out_path = DATA_DIR / "pa_setups_labeled.parquet"
    feat_df.to_parquet(out_path, index=False)

    schema_report = {
        "schema_version": InstitutionalFeatureStore.SCHEMA_VERSION,
        "feature_count": len(FEATURES),
        "features": list(FEATURES),
        "total_rows": total,
        "missing_by_feature": missing_counts,
        "missing_ratio_by_feature": {
            k: round(v / max(total, 1), 6) for k, v in missing_counts.items()
        },
        "all_rows_complete": all(v == 0 for v in missing_counts.values()),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = LOG_DIR / "feature_schema_report.json"
    schema_path.write_text(json.dumps(schema_report, indent=2), encoding="utf-8")
    emit(f"Feature schema report: {schema_path}")
    return feat_df, schema_report


def task4_quality_audit(feat_df: pd.DataFrame, schema_report: dict[str, Any]) -> dict[str, Any]:
    emit("TASK 4 — Data Quality Audit")
    from tradingbot.ml.feature_store import FEATURES

    lines: list[str] = []
    lines.append("PHASE 12A — Data Quality Audit")
    lines.append(f"Generated UTC: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    audit: dict[str, Any] = {"total_rows": len(feat_df)}

    if feat_df.empty:
        lines.append("ERROR: empty dataset")
        audit["error"] = "empty"
        report_path = LOG_DIR / "data_quality_report.txt"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return audit

    dup_ids = int(feat_df["setup_id"].duplicated().sum())
    dup_ts_dir = int(
        feat_df.duplicated(subset=["timestamp_utc", "timeframe", "direction"]).sum()
    )
    audit["duplicate_setup_id"] = dup_ids
    audit["duplicate_timestamp_direction"] = dup_ts_dir
    lines.append(f"duplicate_setup_id={dup_ids}")
    lines.append(f"duplicate_timestamp+direction={dup_ts_dir}")

    missing_feat = 0
    for f in FEATURES:
        if f not in feat_df.columns:
            missing_feat += len(feat_df)
            continue
        missing_feat += int(feat_df[f].isna().sum())
    total_cells = len(feat_df) * len(FEATURES)
    missing_ratio = missing_feat / max(total_cells, 1)
    audit["missing_feature_ratio"] = round(missing_ratio, 6)
    lines.append(f"missing_feature_ratio={missing_ratio:.6f}")

    nan_report: dict[str, float] = {}
    for f in FEATURES:
        if f in feat_df.columns:
            nan_report[f] = round(float(feat_df[f].isna().mean()), 6)
    audit["nan_ratios"] = nan_report
    lines.append("NaN ratios (top):")
    for f, r in sorted(nan_report.items(), key=lambda x: -x[1])[:5]:
        lines.append(f"  {f}={r}")

    bad_prices = int(
        (feat_df["entry_price"] <= 0).sum()
        + (feat_df["stop_price"] <= 0).sum()
        + (feat_df["tp_price"] <= 0).sum()
    )
    audit["impossible_prices"] = bad_prices
    lines.append(f"impossible_prices={bad_prices}")

    neg_stop = int((feat_df["entry_price"] == feat_df["stop_price"]).sum())
    audit["zero_stop_distance"] = neg_stop
    lines.append(f"zero_stop_distance={neg_stop}")

    invalid_stops = 0
    for _, r in feat_df.iterrows():
        entry, sl = float(r["entry_price"]), float(r["stop_price"])
        if r["direction"] == "BUY" and sl >= entry:
            invalid_stops += 1
        elif r["direction"] == "SELL" and sl <= entry:
            invalid_stops += 1
    audit["invalid_stop_direction"] = invalid_stops
    lines.append(f"invalid_stop_direction={invalid_stops}")

    leakage_flags: list[str] = []
    if "bars_to_outcome" in feat_df.columns:
        same_bar = feat_df[feat_df["bars_to_outcome"] == 0]
        if len(same_bar) > 0:
            leakage_flags.append(f"same_bar_outcome={len(same_bar)}")
    future_ts = feat_df[feat_df["timestamp_utc"] > feat_df["timestamp_utc"].max()]
    if len(future_ts) > 0:
        leakage_flags.append("future_timestamps")
    audit["leakage_detected"] = len(leakage_flags) > 0
    audit["leakage_flags"] = leakage_flags
    lines.append(f"leakage_detected={audit['leakage_detected']} flags={leakage_flags}")

    dup_rate = dup_ids / max(len(feat_df), 1)
    audit["duplicate_rate"] = round(dup_rate, 6)
    lines.append(f"duplicate_rate={dup_rate:.6f}")

    all_stops_valid = invalid_stops == 0 and neg_stop == 0
    audit["all_stop_distances_valid"] = all_stops_valid
    lines.append(f"all_stop_distances_valid={all_stops_valid}")

    report_path = LOG_DIR / "data_quality_report.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    emit(f"Quality report: {report_path}")
    return audit


def task5_regime_distribution(feat_df: pd.DataFrame) -> dict[str, Any]:
    emit("TASK 5 — Regime Balancing")
    from tradingbot.ml.feature_store import FEATURES

    distribution: dict[str, Any] = {"generated_at_utc": datetime.now(timezone.utc).isoformat()}
    for regime in ("TREND", "EXPANSION", "RANGING"):
        subset = feat_df[feat_df["regime"] == regime] if "regime" in feat_df.columns else pd.DataFrame()
        wins = subset[subset["label"] == 1] if "label" in subset.columns else pd.DataFrame()
        win_rate = len(wins) / max(len(subset), 1)
        avg_r = float(subset["realized_r_multiple"].mean()) if len(subset) and "realized_r_multiple" in subset else 0.0
        feat_complete = 1.0
        if len(subset):
            miss = sum(subset[f].isna().sum() for f in FEATURES if f in subset.columns)
            feat_complete = 1.0 - miss / max(len(subset) * len(FEATURES), 1)
        distribution[regime] = {
            "sample_count": int(len(subset)),
            "win_rate": round(win_rate, 4),
            "avg_r_multiple": round(avg_r, 4),
            "feature_completeness": round(feat_complete, 4),
        }

    path = LOG_DIR / "regime_distribution.json"
    path.write_text(json.dumps(distribution, indent=2), encoding="utf-8")
    emit(f"Regime distribution: {path}")
    return distribution


def task6_certification(
    feat_df: pd.DataFrame,
    audit: dict[str, Any],
    regime_dist: dict[str, Any],
) -> dict[str, Any]:
    emit("TASK 6 — Institutional Readiness Gate")

    total_setups = len(feat_df)
    labeled = int(feat_df["label"].isin([0, 1, -1]).sum()) if "label" in feat_df.columns else 0
    trend_n = regime_dist.get("TREND", {}).get("sample_count", 0)
    expansion_n = regime_dist.get("EXPANSION", {}).get("sample_count", 0)
    ranging_n = regime_dist.get("RANGING", {}).get("sample_count", 0)
    dup_rate = float(audit.get("duplicate_rate", 1.0))
    miss_ratio = float(audit.get("missing_feature_ratio", 1.0))
    leakage = bool(audit.get("leakage_detected", True))
    stops_valid = bool(audit.get("all_stop_distances_valid", False))

    checks = {
        "total_labeled_gte_800": total_setups >= 800,
        "each_regime_gte_150": min(trend_n, expansion_n, ranging_n) >= 150,
        "duplicate_rate_lt_0.1pct": dup_rate < 0.001,
        "missing_feature_lt_1pct": miss_ratio < 0.01,
        "no_leakage": not leakage,
        "valid_stops": stops_valid,
    }
    ready = all(checks.values())

    blockers = [k for k, v in checks.items() if not v]

    result = {
        "TOTAL_SETUPS": total_setups,
        "TOTAL_LABELED": labeled,
        "TREND_SAMPLES": trend_n,
        "EXPANSION_SAMPLES": expansion_n,
        "RANGING_SAMPLES": ranging_n,
        "DUPLICATE_RATE": round(dup_rate, 6),
        "MISSING_FEATURE_RATIO": round(miss_ratio, 6),
        "LEAKAGE_DETECTED": "YES" if leakage else "NO",
        "INSTITUTIONAL_DATASET_READY": "YES" if ready else "NO",
        "checks": checks,
        "blockers": blockers,
    }

    lines = [
        "PHASE_12A_RESULT",
        f"TOTAL_SETUPS={total_setups}",
        f"TOTAL_LABELED={labeled}",
        f"TREND_SAMPLES={trend_n}",
        f"EXPANSION_SAMPLES={expansion_n}",
        f"RANGING_SAMPLES={ranging_n}",
        f"DUPLICATE_RATE={dup_rate:.6f}",
        f"MISSING_FEATURE_RATIO={miss_ratio:.6f}",
        f"LEAKAGE_DETECTED={'YES' if leakage else 'NO'}",
        f"INSTITUTIONAL_DATASET_READY={'YES' if ready else 'NO'}",
    ]
    if blockers:
        lines.append(f"BLOCKERS={','.join(blockers)}")

    result_path = LOG_DIR / "phase12a_result.txt"
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        emit(line)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PHASE 12A PA dataset builder")
    parser.add_argument("--skip-extract", action="store_true", help="Reuse pa_setups_raw.parquet")
    parser.add_argument("--sequential", action="store_true", help="Disable parallel extraction")
    args = parser.parse_args()

    from tradingbot.config.dotenv_loader import load_dotenv

    load_dotenv()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    emit(f"PHASE 12A PA Dataset Builder | UTC {datetime.now(timezone.utc).isoformat()}")
    emit(f"USE_ML_KERNEL={os.environ.get('USE_ML_KERNEL', 'false')}")
    emit("")

    raw_path = DATA_DIR / "pa_setups_raw.parquet"
    if args.skip_extract and raw_path.is_file():
        emit(f"Skipping extraction — loading {raw_path}")
        raw_df = pd.read_parquet(raw_path)
    else:
        raw_df = task1_extract_all(parallel=not args.sequential)

    labeled_path = DATA_DIR / "pa_setups_labeled.parquet"
    if args.skip_extract and labeled_path.is_file() and not (LOG_DIR / "feature_schema_report.json").is_file():
        emit(f"Skipping label — loading {labeled_path}")
        labeled_df = pd.read_parquet(labeled_path)
    else:
        labeled_df = task2_label(raw_df)
    feat_df, schema_report = task3_features(labeled_df)
    audit = task4_quality_audit(feat_df, schema_report)
    regime_dist = task5_regime_distribution(feat_df)
    result = task6_certification(feat_df, audit, regime_dist)

    emit("")
    emit("Deliverables:")
    for p in (
        DATA_DIR / "pa_setups_raw.parquet",
        DATA_DIR / "pa_setups_labeled.parquet",
        LOG_DIR / "data_quality_report.txt",
        LOG_DIR / "regime_distribution.json",
        LOG_DIR / "feature_schema_report.json",
        LOG_DIR / "phase12a_result.txt",
    ):
        emit(f"  {p} exists={p.is_file()}")

    return 0 if result["INSTITUTIONAL_DATASET_READY"] == "YES" else 2


if __name__ == "__main__":
    raise SystemExit(main())
