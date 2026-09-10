"""Phase 54 — model sweep on strict walk-forward (research only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase54" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

MODELS = ["logistic", "random_forest", "hist_gradient_boosting"]


def _create_model(name: str, seed: int = 42):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    if name == "logistic":
        return LogisticRegression(max_iter=500, class_weight="balanced", random_state=seed)
    if name == "random_forest":
        return RandomForestClassifier(n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(max_iter=120, max_depth=6, random_state=seed)
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model
    return create_trend_ml_model(name, seed=seed)


def strict_walk_forward_models(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    model_names: list[str],
    *,
    seed: int = 42,
) -> dict[str, Any]:
    """Run strict WF for each model; return comparison table."""
    from tradingbot.ml.research.phase50.strict_walk_forward import strict_walk_forward

    results: list[dict[str, Any]] = []
    for name in model_names:
        if name == "hist_gradient_boosting":
            row = _run_hgb_wf(df, label_col, feature_cols, seed=seed)
        else:
            row = strict_walk_forward(df, label_col, feature_cols, model_name=name, seed=seed)
        results.append({
            "model": name,
            "verdict": row.get("verdict"),
            "gate_passed": row.get("gate_passed", False),
            "mean_pf": row.get("mean_pf"),
            "mean_auc": row.get("mean_auc"),
            "windows": len(row.get("walk_forward_windows") or []),
        })

    best = max(results, key=lambda x: (float(x.get("mean_pf") or 0), float(x.get("mean_auc") or 0)))
    return {"models": results, "best_model": best["model"], "best_mean_pf": best.get("mean_pf"), "best_mean_auc": best.get("mean_auc")}


def _run_hgb_wf(df: pd.DataFrame, label_col: str, feature_cols: list[str], *, seed: int = 42) -> dict[str, Any]:
    """HistGradientBoosting not in trend_ml factory — inline WF."""
    import numpy as np
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf

    work = df[df[label_col].isin([0, 1])].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())
    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    windows: list[dict] = []

    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < 200 or len(te) < 100:
            continue
        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)
        y_te = te[label_col].astype(int).values
        scaler = StandardScaler()
        model = _create_model("hist_gradient_boosting", seed=seed)
        model.fit(scaler.fit_transform(X_tr), y_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]
        try:
            auc = round(float(roc_auc_score(y_te, proba)), 4)
        except ValueError:
            auc = 0.5
        sweep = [{"threshold": t, **_pf(y_te, proba, t)} for t in thresholds]
        eligible = [s for s in sweep if s["trades"] >= 15]
        best = max(eligible, key=lambda x: (x["pf"], x["trades"])) if eligible else max(sweep, key=lambda x: x["trades"])
        windows.append({"test_year": int(test_year), "auc": auc, "best_pf": best["pf"], "best_trades": best["trades"]})

    if len(windows) < 3:
        return {"verdict": "INSUFFICIENT_WINDOWS", "walk_forward_windows": windows}
    pfs = [float(w["best_pf"]) for w in windows]
    aucs = [float(w["auc"]) for w in windows]
    mean_pf = round(float(np.mean(pfs)), 4)
    mean_auc = round(float(np.mean(aucs)), 4)
    gates = {"mean_pf_ge_1_3": mean_pf >= 1.3, "mean_auc_ge_0_55": mean_auc >= 0.55}
    verdict = "STRICT_GATE_PASS" if all(gates.values()) else "STRICT_GATE_FAIL"
    return {"verdict": verdict, "gate_passed": all(gates.values()), "mean_pf": mean_pf, "mean_auc": mean_auc, "walk_forward_windows": windows}


def regime_threshold_research(df: pd.DataFrame, label_col: str, feature_cols: list[str], *, model_name: str = "random_forest") -> dict[str, Any]:
    """Per-regime optimal threshold research (no production changes)."""
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

    if "regime" not in df.columns:
        return {"verdict": "NO_REGIME_COLUMN"}

    work = df[df[label_col].isin([0, 1])].copy()
    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50]
    by_regime: dict[str, dict] = {}

    for regime, grp in work.groupby("regime"):
        if len(grp) < 200:
            continue
        split = int(len(grp) * 0.8)
        tr, te = grp.iloc[:split], grp.iloc[split:]
        if len(te) < 50:
            continue
        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)
        y_te = te[label_col].astype(int).values
        scaler = StandardScaler()
        model = create_trend_ml_model(model_name)
        model.fit(scaler.fit_transform(X_tr), y_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]
        best_thr, best_pf = 0.35, 0.0
        for t in thresholds:
            row = _pf(y_te, proba, t)
            if row["trades"] >= 10 and row["pf"] > best_pf:
                best_pf, best_thr = row["pf"], t
        by_regime[str(regime)] = {"best_threshold": best_thr, "best_pf": best_pf, "test_rows": len(te)}

    return {"verdict": "REGIME_THRESHOLDS_COMPUTED", "by_regime": by_regime}


def run_phase54() -> dict:
    from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    feats = feature_columns(df)
    sweep = strict_walk_forward_models(df, "label_v3", feats, MODELS)
    regime = regime_threshold_research(df, "label_v3", feats, model_name=sweep.get("best_model", "random_forest"))

    verdict = "MODEL_SWEEP_COMPLETE"
    if float(sweep.get("best_mean_pf") or 0) >= 1.3:
        verdict = "CANDIDATE_FOUND"

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "features": len(feats),
        "rows": len(df),
        "model_sweep": sweep,
        "regime_calibration": regime,
        "research_only": True,
    }


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "model_sweep.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("  wrote phase54/artifacts/model_sweep.json", flush=True)
    report = {
        "phase": "54",
        "title": "Model Sweep (Research Only)",
        "title_fa": "اسکن مدل (فقط پژوهش)",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "model_sweep": data.get("model_sweep"),
        "regime_calibration": data.get("regime_calibration"),
        "research_only": True,
    }
    (ROOT / "phase54_final_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("  wrote phase54_final_report.json", flush=True)


def main() -> None:
    data = run_phase54()
    write_all(data)
    print(json.dumps({
        "verdict": data["verdict"],
        "best_model": (data.get("model_sweep") or {}).get("best_model"),
        "best_mean_pf": (data.get("model_sweep") or {}).get("best_mean_pf"),
    }, indent=2))


if __name__ == "__main__":
    main()
