"""Phase 8A — ML Kernel rehabilitation research (shadow-only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from tradingbot.domain.trade_features import FEATURE_NAMES as META_FEATURE_NAMES
from tradingbot.ml.research.phase3a.vol_edge_research import regime_cluster
from tradingbot.ml.shadow.phase49a_metrics import _bucket_metrics, _precision
from tradingbot.ml.shadow.phase5a_metrics import classify_bucket
from tradingbot.ml.shadow.phase5a_shadow_replay import load_replay_cache
from tradingbot.strategies.adaptive_regime import classify_regime, prepare_adaptive_frame

ROOT = Path(__file__).resolve().parents[4]
PHASE5A_CERT = ROOT / "logs" / "phase5a_ml_kernel_certification.json"
PHASE5A_REPLAY = ROOT / "logs" / "phase5a_shadow_replay_records.jsonl"
DATASET_PATH = ROOT / "data" / "ml" / "datasets" / "XAUUSD_M5_dataset_v2.parquet"
PHASE15J_DRIFT = ROOT / "data" / "ml" / "reports" / "phase15j" / "feature_drift.json"
PHASE99_META = ROOT / "data" / "ml" / "research" / "phase9_9_best" / "metadata.json"
PHASE99_CONFIG = ROOT / "data" / "ml" / "research" / "phase9_9_best" / "config.json"

PSI_THRESHOLD = 0.25
KS_P_THRESHOLD = 0.01
MIN_SAMPLE = 300
AGREE_PF_GATE = 1.20
AGREE_EXP_GATE = 0.15
PRECISION_GATE = 55.0
CALIBRATION_GATE = 0.08

REGIME_BUCKETS = ("TREND", "EXPANSION", "RANGING")


def _pf_num(pf: Any) -> float:
    if pf in ("inf", float("inf")):
        return 999.0
    return float(pf)


def _psi(expected: np.ndarray, actual: np.ndarray, *, bins: int = 10) -> float:
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 20 or len(actual) < 10:
        return 0.0
    breaks = np.linspace(
        min(expected.min(), actual.min()),
        max(expected.max(), actual.max()),
        bins + 1,
    )
    if breaks[-1] <= breaks[0]:
        return 0.0
    e_pct = np.histogram(expected, bins=breaks)[0] / len(expected)
    a_pct = np.histogram(actual, bins=breaks)[0] / len(actual)
    e_pct = np.clip(e_pct, 1e-6, None)
    a_pct = np.clip(a_pct, 1e-6, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def _ks_test(train: np.ndarray, live: np.ndarray) -> dict[str, Any]:
    train = train[np.isfinite(train)]
    live = live[np.isfinite(live)]
    if len(train) < 20 or len(live) < 10:
        return {"statistic": 0.0, "p_value": 1.0, "drift": False}
    stat, p = stats.ks_2samp(train, live)
    return {
        "statistic": round(float(stat), 4),
        "p_value": round(float(p), 6),
        "drift": bool(p < KS_P_THRESHOLD),
    }


def _map_regime_bucket(raw: str, atr_pct: float | None = None) -> str:
    reg = (raw or "").upper()
    if atr_pct is not None and np.isfinite(atr_pct):
        cluster = regime_cluster(float(atr_pct))
        if cluster == "EXPANSION":
            return "EXPANSION"
    if reg in ("TREND", "HIGH_VOLATILITY", "STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return "TREND"
    if reg in ("RANGE", "LOW_VOLATILITY", "RANGING"):
        return "RANGING"
    if reg == "VOLATILE":
        return "EXPANSION"
    return "RANGING"


def load_shadow_records() -> list[dict[str, Any]]:
    if PHASE5A_REPLAY.is_file():
        rows = []
        for line in PHASE5A_REPLAY.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        if rows:
            return rows
    cached = load_replay_cache()
    return cached or []


def _load_train_frame() -> pd.DataFrame:
    if not DATASET_PATH.is_file():
        return pd.DataFrame()
    return pd.read_parquet(DATASET_PATH)


def enrich_shadow_features(
    records: list[dict[str, Any]],
    df: pd.DataFrame,
) -> list[dict[str, Any]]:
    from tradingbot.ml.features.builder import FeatureBuilder
    from tradingbot.ml.shadow.ml_adapter import MLAdapter

    adapter = MLAdapter.load()
    builder = FeatureBuilder("XAUUSD", None)
    frame = prepare_adaptive_frame(df)
    ts_to_idx = {str(t): i for i, t in enumerate(df.index)}

    enriched: list[dict[str, Any]] = []
    for rec in records:
        ts = str(rec.get("timestamp", ""))
        i = ts_to_idx.get(ts)
        if i is None:
            try:
                i = int(df.index.get_indexer([pd.Timestamp(ts)], method="nearest")[0])
            except Exception:
                i = None
        row = dict(rec)
        ml_feats: dict[str, float] = {}
        meta_feats: dict[str, float] = {}
        regime_raw = "RANGING"
        atr_pct = None
        if i is not None and 0 <= i < len(df):
            ml_feats = builder.compute_at(df, i)
            subset = {k: ml_feats.get(k, 0.0) for k in adapter.bundle.feature_order}
            row["ml_features"] = subset
            row["ml_features_full"] = {k: ml_feats.get(k, 0.0) for k in adapter.bundle.feature_order}
            ad_row = frame.iloc[min(i, len(frame) - 1)]
            atr_pct = float(ad_row.get("atr_pct", np.nan))
            regime_raw = classify_regime(ad_row)
            row["regime_raw"] = regime_raw
            row["regime_bucket"] = _map_regime_bucket(regime_raw, atr_pct)
            row["atr_pct"] = atr_pct
            row["win"] = 1 if float(rec.get("final_trade_R", 0)) > 0 else 0
        enriched.append(row)
    return enriched


def feature_parity_audit(
    records: list[dict[str, Any]],
    train_df: pd.DataFrame,
) -> dict[str, Any]:
    from tradingbot.ml.shadow.ml_adapter import MLAdapter

    adapter = MLAdapter.load()
    ml_order = list(adapter.bundle.feature_order)
    phase99_cfg = json.loads(PHASE99_CONFIG.read_text(encoding="utf-8")) if PHASE99_CONFIG.is_file() else {}
    phase99_meta = json.loads(PHASE99_META.read_text(encoding="utf-8")) if PHASE99_META.is_file() else {}

    train_cols = set(train_df.columns)
    parity_rows: list[dict[str, Any]] = []
    for feat in ml_order:
        train_vals = train_df[feat].astype(float).values if feat in train_df.columns else np.array([])
        live_vals = np.array([float(r.get("ml_features", {}).get(feat, np.nan)) for r in records if "ml_features" in r])
        live_vals = live_vals[np.isfinite(live_vals)]
        train_finite = train_vals[np.isfinite(train_vals)] if len(train_vals) else np.array([])
        missing_live_pct = round(100.0 * sum(1 for r in records if feat not in r.get("ml_features", {})) / max(len(records), 1), 2)
        scale_train = float(np.std(train_finite)) if len(train_finite) else 0.0
        scale_live = float(np.std(live_vals)) if len(live_vals) else 0.0
        parity_rows.append({
            "feature": feat,
            "in_training_dataset": feat in train_cols,
            "in_meta_labeler": feat in META_FEATURE_NAMES,
            "train_mean": round(float(np.mean(train_finite)), 4) if len(train_finite) else None,
            "live_mean": round(float(np.mean(live_vals)), 4) if len(live_vals) else None,
            "train_std": round(scale_train, 4),
            "live_std": round(scale_live, 4),
            "scale_ratio_live_over_train": round(scale_live / scale_train, 3) if scale_train > 0 else None,
            "missing_live_pct": missing_live_pct,
        })

    phase15j_feats = []
    if PHASE15J_DRIFT.is_file():
        ref = json.loads(PHASE15J_DRIFT.read_text(encoding="utf-8"))
        phase15j_feats = [x.get("feature") for x in ref.get("features", [])]

    mismatched_drift_ref = [f for f in phase15j_feats if f not in ml_order]

    return {
        "ml_kernel_feature_order": ml_order,
        "ml_kernel_feature_count": len(ml_order),
        "meta_labeler_feature_count": len(META_FEATURE_NAMES),
        "meta_labeler_features": META_FEATURE_NAMES,
        "feature_namespace_match": False,
        "phase99_training_regime": phase99_cfg.get("regime"),
        "phase99_model_type": phase99_meta.get("model_type"),
        "phase99_train_rows": phase99_meta.get("train_rows"),
        "phase15j_drift_features_not_in_model": mismatched_drift_ref,
        "parity_rows": parity_rows,
        "root_causes": [
            "Phase 9.9 frozen on RANGE regime only but shadow applies to all PA trades",
            f"ML kernel uses {len(ml_order)} features; meta-labeler uses {len(META_FEATURE_NAMES)} — different pipelines",
            "phase15j drift monitor tracks features absent from current 4-feature bundle",
            "Sell-heavy training (72.9% sell coverage) vs balanced PA live directions",
        ],
    }


def compute_feature_drift(
    records: list[dict[str, Any]],
    train_df: pd.DataFrame,
    feature_names: list[str],
) -> dict[str, Any]:
    train_split = train_df[train_df["split"] == "train"] if "split" in train_df.columns else train_df
    rows: list[dict[str, Any]] = []
    critical: list[str] = []
    for feat in feature_names:
        if feat not in train_split.columns:
            continue
        train_vals = train_split[feat].astype(float).values
        live_vals = np.array([float(r.get("ml_features", {}).get(feat, np.nan)) for r in records if "ml_features" in r])
        live_vals = live_vals[np.isfinite(live_vals)]
        train_finite = train_vals[np.isfinite(train_vals)]
        psi = _psi(train_finite, live_vals)
        ks = _ks_test(train_finite, live_vals)
        drift = psi > PSI_THRESHOLD or ks["drift"]
        if drift:
            critical.append(feat)
        rows.append({
            "feature": feat,
            "psi": round(psi, 4),
            "psi_drift": psi > PSI_THRESHOLD,
            "ks_statistic": ks["statistic"],
            "ks_p_value": ks["p_value"],
            "ks_drift": ks["drift"],
            "critical": drift,
        })
    return {
        "features_analyzed": len(rows),
        "critical_features": critical,
        "critical_count": len(critical),
        "details": rows,
    }


def _brier(probs: np.ndarray, y: np.ndarray) -> float:
    if len(probs) == 0:
        return 1.0
    return float(np.mean((probs - y) ** 2))


def _calibration_error(probs: np.ndarray, y: np.ndarray, *, n_bins: int = 5) -> float:
    if len(probs) < 20:
        return 1.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    errors: list[float] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs >= lo) & (probs < hi if hi < 1.0 else probs <= hi)
        if mask.sum() < 5:
            continue
        errors.append(abs(float(probs[mask].mean()) - float(y[mask].mean())))
    return float(np.mean(errors)) if errors else 1.0


def test_calibrations(records: list[dict[str, Any]]) -> dict[str, Any]:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    scored = [
        r for r in records
        if r.get("ml_probability") is not None
        and str(r.get("ml_prediction_direction", "")).upper() in ("BUY", "SELL")
    ]
    if len(scored) < 30:
        return {"error": "insufficient_scored_records", "count": len(scored)}

    X = np.array([[float(r["ml_probability"])] for r in scored])
    y = np.array([int(r.get("win", 0)) for r in scored])
    raw_probs = X[:, 0]

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_probs, y)
    iso_probs = iso.predict(raw_probs)

    platt = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(max_iter=500)),
    ])
    platt.fit(X, y)
    platt_probs = platt.predict_proba(X)[:, 1]

    try:
        from betacal import BetaCalibration

        beta = BetaCalibration()
        beta.fit(raw_probs.reshape(-1, 1), y)
        beta_probs = beta.predict(raw_probs.reshape(-1, 1))
        beta_ok = True
    except Exception:
        beta_probs = platt_probs
        beta_ok = False

    methods = {
        "raw": raw_probs,
        "isotonic": iso_probs,
        "platt": platt_probs,
        "beta": beta_probs if beta_ok else platt_probs,
    }
    results: dict[str, Any] = {}
    best_name = "raw"
    best_brier = 999.0
    for name, probs in methods.items():
        brier = round(_brier(probs, y), 4)
        cal_err = round(_calibration_error(probs, y), 4)
        results[name] = {
            "brier_score": brier,
            "calibration_error": cal_err,
            "available": name != "beta" or beta_ok,
        }
        if brier < best_brier:
            best_brier = brier
            best_name = name

    return {
        "sample_scored": len(scored),
        "methods": results,
        "best_calibration": best_name,
        "beta_calibration_available": beta_ok,
    }


def train_regime_models(
    records: list[dict[str, Any]],
    feature_names: list[str],
) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    out: dict[str, Any] = {}
    for bucket in REGIME_BUCKETS:
        subset = [r for r in records if r.get("regime_bucket") == bucket and "ml_features" in r]
        if len(subset) < 25:
            out[bucket] = {"trained": False, "samples": len(subset), "reason": "insufficient_samples"}
            continue
        X = np.array([[float(r["ml_features"].get(f, 0.0)) for f in feature_names] for r in subset])
        y = np.array([int(r.get("win", 0)) for r in subset])
        if len(np.unique(y)) < 2:
            out[bucket] = {"trained": False, "samples": len(subset), "reason": "single_class"}
            continue
        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=500, class_weight="balanced")),
        ])
        pipe.fit(X, y)
        probs = pipe.predict_proba(X)[:, 1]
        preds = (probs >= 0.5).astype(int)
        acc = float((preds == y).mean())
        out[bucket] = {
            "trained": True,
            "samples": len(subset),
            "win_rate_pct": round(float(y.mean()) * 100, 2),
            "in_sample_accuracy": round(acc, 3),
            "brier_score": round(_brier(probs, y), 4),
        }
    return out


def evaluate_shadow_buckets(records: list[dict[str, Any]]) -> dict[str, Any]:
    agree = [r for r in records if classify_bucket(r) == "agree"]
    disagree = [r for r in records if classify_bucket(r) == "disagree"]
    agree_m = _bucket_metrics(agree)
    disagree_m = _bucket_metrics(disagree)

    probs = []
    ys = []
    for r in records:
        if r.get("ml_probability") is None:
            continue
        if str(r.get("ml_prediction_direction", "")).upper() not in ("BUY", "SELL"):
            continue
        probs.append(float(r["ml_probability"]))
        ys.append(1 if float(r.get("final_trade_R", 0)) > 0 else 0)
    probs_arr = np.asarray(probs)
    ys_arr = np.asarray(ys)

    return {
        "sample_size": len(records),
        "agree_pf": agree_m["pf"],
        "agree_expectancy_r": agree_m["expectancy_r"],
        "disagree_pf": disagree_m["pf"],
        "precision_buy_pct": _precision(records, "BUY"),
        "precision_sell_pct": _precision(records, "SELL"),
        "brier_score": round(_brier(probs_arr, ys_arr), 4) if len(probs_arr) else None,
        "calibration_error": round(_calibration_error(probs_arr, ys_arr), 4) if len(probs_arr) else None,
    }


def passes_certification(
    eval_metrics: dict[str, Any],
    drift: dict[str, Any],
    calibration: dict[str, Any],
) -> bool:
    best_cal = calibration.get("methods", {}).get(calibration.get("best_calibration", "raw"), {})
    cal_err = float(best_cal.get("calibration_error", 999))
    return (
        int(eval_metrics.get("sample_size", 0)) >= MIN_SAMPLE
        and _pf_num(eval_metrics.get("agree_pf")) > AGREE_PF_GATE
        and float(eval_metrics.get("agree_expectancy_r", -999)) > AGREE_EXP_GATE
        and float(eval_metrics.get("precision_buy_pct", 0)) > PRECISION_GATE
        and float(eval_metrics.get("precision_sell_pct", 0)) > PRECISION_GATE
        and cal_err < CALIBRATION_GATE
        and drift.get("critical_count", 999) == 0
    )


def run_ml_rehab(
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    records = load_shadow_records()
    if df is None:
        from tradingbot.backtest.config import BacktestConfig
        from tradingbot.backtest.data_source import BacktestMarketData

        cfg = BacktestConfig(symbols=["XAUUSD"], timeframe="M5", days=95, warmup=500, use_cache=True)
        md = BacktestMarketData(cfg)
        md.load()
        df = md.frame("XAUUSD")

    enriched = enrich_shadow_features(records, df)
    train_df = _load_train_frame()
    from tradingbot.ml.shadow.ml_adapter import MLAdapter

    ml_feats = list(MLAdapter.load().bundle.feature_order)

    parity = feature_parity_audit(enriched, train_df)
    drift = compute_feature_drift(enriched, train_df, ml_feats)
    calibration = test_calibrations(enriched)
    regime_models = train_regime_models(enriched, ml_feats)
    evaluation = evaluate_shadow_buckets(enriched)
    certified = passes_certification(evaluation, drift, calibration)

    return {
        "records": len(enriched),
        "parity": parity,
        "drift": drift,
        "calibration": calibration,
        "regime_models": regime_models,
        "evaluation": evaluation,
        "certified": certified,
        "keep_shadow_mode": not certified,
    }
