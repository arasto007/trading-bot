"""Phase 5A — drift analysis (train vs shadow live/replay)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
TRAIN_DRIFT_PATH = ROOT / "data" / "ml" / "reports" / "phase15j" / "feature_drift.json"
TRAIN_META_PATH = ROOT / "data" / "ml" / "research" / "phase9_9_best" / "metadata.json"
DATASET_PATH = ROOT / "data" / "ml" / "datasets" / "XAUUSD_M5_dataset_v2.parquet"

PSI_DRIFT_THRESHOLD = 0.25
CALIBRATION_DRIFT_THRESHOLD = 0.15


def _psi(expected: np.ndarray, actual: np.ndarray, *, bins: int = 10) -> float:
    """Population Stability Index between two distributions."""
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 20 or len(actual) < 20:
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


def _confidence_distribution(probs: list[float]) -> dict[str, Any]:
    if not probs:
        return {"count": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0}
    arr = np.asarray(probs, dtype=float)
    return {
        "count": int(len(arr)),
        "mean": round(float(arr.mean()), 4),
        "p50": round(float(np.percentile(arr, 50)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
    }


def _calibration_error(records: list[dict[str, Any]], *, n_bins: int = 5) -> float:
    """Mean |predicted_prob - observed_win_rate| across probability bins."""
    scored: list[tuple[float, int]] = []
    for r in records:
        prob = r.get("ml_probability")
        ml_dir = str(r.get("ml_prediction_direction", "HOLD")).upper()
        if prob is None or ml_dir not in ("BUY", "SELL"):
            continue
        win = 1 if float(r.get("final_trade_R", 0)) > 0 else 0
        scored.append((float(prob), win))
    if len(scored) < 20:
        return 0.0
    arr = np.asarray(scored)
    probs = arr[:, 0]
    wins = arr[:, 1]
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    errors: list[float] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs >= lo) & (probs < hi if hi < 1.0 else probs <= hi)
        if mask.sum() < 5:
            continue
        pred = float(probs[mask].mean())
        obs = float(wins[mask].mean())
        errors.append(abs(pred - obs))
    return round(float(np.mean(errors)), 4) if errors else 0.0


def analyze_drift(
    records: list[dict[str, Any]],
    *,
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    """
    Compare train vs shadow:
    - feature distribution (from frozen phase15j + dataset v2)
    - prediction confidence distribution
    - calibration drift
    """
    ds_path = dataset_path or DATASET_PATH
    train_probs: list[float] = []
    live_probs = [
        float(r["ml_probability"])
        for r in records
        if r.get("ml_probability") is not None
    ]

    train_meta: dict[str, Any] = {}
    if TRAIN_META_PATH.is_file():
        train_meta = json.loads(TRAIN_META_PATH.read_text(encoding="utf-8"))
        pm = train_meta.get("probability_metrics") or {}
        train_probs = [float(pm.get("min_probability", 0.1)), float(pm.get("max_probability", 0.9))]

    feature_drift_rows: list[dict[str, Any]] = []
    if TRAIN_DRIFT_PATH.is_file():
        ref = json.loads(TRAIN_DRIFT_PATH.read_text(encoding="utf-8"))
        for row in ref.get("features", []):
            feature_drift_rows.append({
                "feature": row.get("feature"),
                "psi": row.get("psi"),
                "feature_drift": row.get("feature_drift"),
            })

    live_conf = _confidence_distribution(live_probs)
    train_conf_dist = {
        "count": int(train_meta.get("train_rows", 0)) if train_meta else 0,
        "probability_std": (train_meta.get("probability_metrics") or {}).get("probability_std"),
        "buy_coverage_pct": (train_meta.get("probability_metrics") or {}).get("buy_coverage_pct"),
        "sell_coverage_pct": (train_meta.get("probability_metrics") or {}).get("sell_coverage_pct"),
    }

    conf_psi = 0.0
    if live_probs and train_meta:
        pm = train_meta.get("probability_metrics") or {}
        std = float(pm.get("probability_std", 0.15) or 0.15)
        mean = 0.5
        synthetic_train = np.random.default_rng(42).normal(mean, std, 500)
        synthetic_train = np.clip(synthetic_train, 0.05, 0.95)
        conf_psi = _psi(synthetic_train, np.asarray(live_probs))

    cal_error = _calibration_error(records)
    drift_detected = conf_psi > PSI_DRIFT_THRESHOLD or cal_error > CALIBRATION_DRIFT_THRESHOLD

    dataset_features: dict[str, Any] = {}
    if ds_path.is_file():
        try:
            df = pd.read_parquet(ds_path, columns=["label"] if "label" in pd.read_parquet(ds_path, columns=[]).columns else None)
            dataset_features["train_rows"] = len(df)
        except Exception:
            dataset_features["train_rows"] = 0

    return {
        "feature_drift_reference": "phase15j",
        "feature_drift_details": feature_drift_rows[:8],
        "train_confidence": train_conf_dist,
        "live_confidence": live_conf,
        "confidence_psi": round(conf_psi, 4),
        "calibration_error": cal_error,
        "calibration_drift_threshold": CALIBRATION_DRIFT_THRESHOLD,
        "drift_detected": drift_detected,
    }
