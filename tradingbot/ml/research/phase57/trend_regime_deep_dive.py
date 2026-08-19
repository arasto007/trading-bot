"""Phase 57B — TREND regime walk-forward deep dive (research only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase57" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

THRESHOLDS = [0.30, 0.35, 0.40, 0.45]
TREND_TOP_FEATURES = [
    "tick_volume_proxy",
    "atr_14",
    "realized_vol_20",
    "rsi_14",
    "macd_histogram",
]


def _load_top_features() -> list[str]:
    r55 = ROOT / "phase55_final_report.json"
    if r55.is_file():
        payload = json.loads(r55.read_text(encoding="utf-8"))
        feats = payload.get("top_features") or []
        if len(feats) >= 5:
            return list(feats[:5])
    return list(TREND_TOP_FEATURES)


def trend_walk_forward_deep_dive(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    thresholds: list[float] | None = None,
    model_name: str = "random_forest",
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = 15,
    seed: int = 42,
) -> dict[str, Any]:
    """Strict walk-forward on TREND subset with fixed threshold grid."""
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

    thresholds = thresholds or THRESHOLDS
    work = df[df[label_col].isin([0, 1])].copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())

    if len(years) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "years": [int(y) for y in years]}

    per_year: list[dict[str, Any]] = []
    threshold_aggregate: dict[float, list[float]] = {t: [] for t in thresholds}

    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < min_train_rows or len(te) < min_test_rows:
            continue

        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)
        y_te = te[label_col].astype(int).values

        scaler = StandardScaler()
        model = create_trend_ml_model(model_name, seed=seed)
        model.fit(scaler.fit_transform(X_tr), y_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]

        try:
            auc = round(float(roc_auc_score(y_te, proba)), 4)
        except ValueError:
            auc = 0.5

        by_threshold: dict[str, dict[str, float | int]] = {}
        for thr in thresholds:
            row = _pf(y_te, proba, thr)
            by_threshold[str(thr)] = row
            if row["trades"] >= min_test_trades:
                threshold_aggregate[thr].append(float(row["pf"]))

        eligible = [
            {"threshold": t, **by_threshold[str(t)]}
            for t in thresholds
            if by_threshold[str(t)]["trades"] >= min_test_trades
        ]
        best = max(eligible, key=lambda x: (x["pf"], x["trades"])) if eligible else max(
            ({"threshold": t, **by_threshold[str(t)]} for t in thresholds),
            key=lambda x: x["trades"],
        )

        per_year.append({
            "test_year": int(test_year),
            "train_rows": len(tr),
            "test_rows": len(te),
            "auc": auc,
            "best_threshold": best["threshold"],
            "best_pf": best["pf"],
            "best_trades": best["trades"],
            "by_threshold": by_threshold,
        })

    if len(per_year) < 3:
        return {
            "verdict": "INSUFFICIENT_WINDOWS",
            "windows_found": len(per_year),
            "per_year": per_year,
        }

    threshold_summary: list[dict[str, Any]] = []
    for thr in thresholds:
        pfs = threshold_aggregate[thr]
        if pfs:
            threshold_summary.append({
                "threshold": thr,
                "mean_pf": round(float(np.mean(pfs)), 4),
                "windows_with_min_trades": len(pfs),
                "per_year_pf": [round(p, 4) for p in pfs],
            })
        else:
            threshold_summary.append({
                "threshold": thr,
                "mean_pf": 0.0,
                "windows_with_min_trades": 0,
                "per_year_pf": [],
            })

    best_overall = max(threshold_summary, key=lambda x: float(x.get("mean_pf") or 0))
    year_pfs = [float(w["best_pf"]) for w in per_year]
    year_aucs = [float(w["auc"]) for w in per_year]
    mean_pf = round(float(np.mean(year_pfs)), 4)
    mean_auc = round(float(np.mean(year_aucs)), 4)

    gate_passed = mean_pf >= 1.3 and mean_auc >= 0.55
    verdict = "TREND_GATE_PASS" if gate_passed else (
        "TREND_GATE_MARGINAL" if mean_pf >= 1.0 else "TREND_GATE_FAIL"
    )

    return {
        "verdict": verdict,
        "regime": "TREND",
        "model": model_name,
        "features_used": feature_cols,
        "feature_count": len(feature_cols),
        "thresholds_tested": thresholds,
        "windows": len(per_year),
        "mean_pf_best_per_year": mean_pf,
        "mean_auc": mean_auc,
        "gate_passed": gate_passed,
        "best_overall": best_overall,
        "threshold_summary": threshold_summary,
        "per_year": per_year,
        "rows_trend": len(work),
    }


def run_trend_regime_deep_dive() -> dict[str, Any]:
    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    feats = _load_top_features()
    available = [c for c in feats if c in df.columns]
    if len(available) < 3:
        from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns
        available = feature_columns(df)[:5]

    dive = trend_walk_forward_deep_dive(df, "label_v3", available)
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **dive,
        "research_only": True,
    }


def write_trend_artifacts(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "trend_regime_deep_dive.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase57/artifacts/trend_regime_deep_dive.json", flush=True)


def main() -> None:
    data = run_trend_regime_deep_dive()
    write_trend_artifacts(data)
    print(json.dumps({
        "verdict": data.get("verdict"),
        "best_threshold": (data.get("best_overall") or {}).get("threshold"),
        "mean_pf": (data.get("best_overall") or {}).get("mean_pf"),
    }, indent=2))


if __name__ == "__main__":
    main()
