"""PHASE 15C — Institutional Calibration Hardening (research only).

Rebuild calibration pipeline on Phase11A + Phase13D datasets/models:
  train base model on chrono train -> fit calibrator on calib -> eval on holdout.
Compare: Platt / Isotonic / Temperature Scaling (+ raw).
Metrics: Brier, ECE, MCE — overall and per TREND / EXPANSION / RANGING.
NO live / routing / config / execution changes.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

ROOT = Path(__file__).resolve().parents[2]
REGIMES = ("TREND", "EXPANSION", "RANGING")
METHODS = ("raw", "platt", "isotonic", "temperature")
PHASES = (
    ("phase11a", ROOT / "data" / "ml" / "research" / "phase11a"),
    ("phase13d", ROOT / "data" / "ml" / "research" / "phase13d"),
)
MIN_TEST_FOR_BEST = 30


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1.0 - p))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -50, 50)
    return 1.0 / (1.0 + np.exp(-z))


def ece_mce(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> tuple[float, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    mce = 0.0
    n = len(y_true)
    if n == 0:
        return 1.0, 1.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        acc = float(y_true[mask].mean())
        conf = float(y_prob[mask].mean())
        gap = abs(conf - acc)
        ece += (cnt / n) * gap
        mce = max(mce, gap)
    return round(float(ece), 6), round(float(mce), 6)


def metrics(y_true: np.ndarray, y_prob: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 0.0, 1.0)
    if len(y_true) == 0:
        return {"brier": 1.0, "ece": 1.0, "mce": 1.0, "n": 0}
    brier = float(brier_score_loss(y_true, y_prob))
    ece, mce = ece_mce(y_true, y_prob)
    return {"brier": round(brier, 6), "ece": ece, "mce": mce, "n": int(len(y_true))}


def fit_platt(p_tr: np.ndarray, y_tr: np.ndarray):
    lr = LogisticRegression(max_iter=1000, solver="lbfgs")
    lr.fit(np.clip(p_tr, 1e-6, 1 - 1e-6).reshape(-1, 1), y_tr)
    return lr


def apply_platt(lr, p: np.ndarray) -> np.ndarray:
    return lr.predict_proba(np.clip(p, 1e-6, 1 - 1e-6).reshape(-1, 1))[:, 1]


def fit_isotonic(p_tr: np.ndarray, y_tr: np.ndarray):
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(np.clip(p_tr, 1e-6, 1 - 1e-6), y_tr)
    return iso


def apply_isotonic(iso, p: np.ndarray) -> np.ndarray:
    return np.asarray(iso.predict(np.clip(p, 1e-6, 1 - 1e-6)), dtype=float)


def fit_temperature(p_tr: np.ndarray, y_tr: np.ndarray) -> float:
    z = _logit(p_tr)
    y = np.asarray(y_tr, dtype=float)
    best_t, best_nll = 1.0, 1e18
    for t in np.concatenate([np.linspace(0.5, 5.0, 46), np.array([0.25, 0.35, 6.0, 8.0, 10.0])]):
        p = np.clip(_sigmoid(z / t), 1e-6, 1 - 1e-6)
        nll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
        if nll < best_nll:
            best_nll = float(nll)
            best_t = float(t)
    return best_t


def apply_temperature(t: float, p: np.ndarray) -> np.ndarray:
    return _sigmoid(_logit(p) / max(t, 1e-6))


def make_model(model_type: str, y_train: np.ndarray):
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
    return RandomForestClassifier(
        n_estimators=250,
        max_depth=6,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )


def feature_cols_for(phase_dir: Path, df: pd.DataFrame) -> list[str]:
    # Prefer phase13d training_matrix / joblib artifact features
    matrix = ROOT / "logs" / "phase13d" / "training_matrix.json"
    if matrix.exists():
        meta = json.loads(matrix.read_text(encoding="utf-8"))
        cols = meta.get("feature_cols") or []
        if cols and all(c in df.columns for c in cols):
            return list(cols)
    # phase11a summary / models
    for art in (phase_dir / "models").glob("*_random_forest.pkl"):
        try:
            import joblib

            obj = joblib.load(art)
            cols = list(obj.get("features") or [])
            if cols and all(c in df.columns for c in cols):
                return cols
        except Exception:
            pass
    # fallback: numeric feature-like columns
    skip = {
        "label",
        "setup_id",
        "timestamp_utc",
        "bar_time",
        "timeframe",
        "direction",
        "entry",
        "entry_price",
        "stop_loss",
        "stop_price",
        "take_profit",
        "tp_price",
        "regime",
        "session_name",
        "realized_r_multiple",
        "r_multiple",
        "bars_to_outcome",
        "exit_reason",
        "timeout",
        "meta_prob",
        "bar_index",
        "source_window_days",
        "rr_target",
        "confluence_score",
    }
    cols = [
        c
        for c in df.columns
        if c not in skip and pd.api.types.is_numeric_dtype(df[c])
    ]
    return cols


def load_dataset(phase_dir: Path, regime: str) -> pd.DataFrame | None:
    path = phase_dir / f"dataset_{regime.lower()}.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if "label" not in df.columns:
        return None
    df = df[df["label"].isin([0, 1])].copy()
    time_col = "timestamp_utc" if "timestamp_utc" in df.columns else ("bar_time" if "bar_time" in df.columns else None)
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], utc=True, format="mixed", errors="coerce")
        df = df.sort_values(time_col).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)
    return df


def triple_split(n: int) -> tuple[int, int]:
    """Return (train_end, calib_end) for ~60/20/20."""
    if n < 25:
        tr = max(10, int(n * 0.5))
        cal = max(tr + 5, int(n * 0.75))
    else:
        tr = int(n * 0.60)
        cal = int(n * 0.80)
    cal = min(max(cal, tr + 5), n - 5)
    tr = min(tr, cal - 5)
    return tr, cal


def evaluate_rebuild(
    *,
    phase: str,
    regime: str,
    model_type: str,
    df: pd.DataFrame,
    feature_cols: list[str],
) -> list[dict[str, Any]]:
    n = len(df)
    tr_end, cal_end = triple_split(n)
    train = df.iloc[:tr_end]
    calib = df.iloc[tr_end:cal_end]
    test = df.iloc[cal_end:]
    if len(test) < 5 or len(calib) < 5 or len(np.unique(train["label"])) < 2:
        return []

    X_tr = train[feature_cols].astype(float).values
    y_tr = train["label"].astype(int).values
    X_ca = calib[feature_cols].astype(float).values
    y_ca = calib["label"].astype(int).values
    X_te = test[feature_cols].astype(float).values
    y_te = test["label"].astype(int).values

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = make_model(model_type, y_tr)
        model.fit(X_tr, y_tr)
        p_ca = np.asarray(model.predict_proba(X_ca)[:, 1], dtype=float)
        p_te = np.asarray(model.predict_proba(X_te)[:, 1], dtype=float)

    if len(np.unique(y_ca)) < 2:
        # cannot fit supervised calibrators meaningfully
        platt = iso = None
        temp = 1.0
    else:
        platt = fit_platt(p_ca, y_ca)
        iso = fit_isotonic(p_ca, y_ca)
        temp = fit_temperature(p_ca, y_ca)

    calibrated = {"raw": p_te}
    if platt is not None:
        calibrated["platt"] = apply_platt(platt, p_te)
        calibrated["isotonic"] = apply_isotonic(iso, p_te)
        calibrated["temperature"] = apply_temperature(temp, p_te)
    else:
        calibrated["platt"] = p_te
        calibrated["isotonic"] = p_te
        calibrated["temperature"] = p_te

    rows = []
    for method, probs in calibrated.items():
        m = metrics(y_te, probs)
        rows.append(
            {
                "phase": phase,
                "regime": regime,
                "model_type": model_type,
                "method": method,
                "temperature": round(temp, 4) if method == "temperature" else None,
                "n_train": int(len(train)),
                "n_calib": int(len(calib)),
                "n_test": int(len(test)),
                "pos_rate_test": round(float(y_te.mean()), 4),
                **m,
            }
        )
    return rows


def certified_row(r: pd.Series | dict) -> bool:
    return bool(float(r["brier"]) < 0.12 and float(r["ece"]) < 0.05 and float(r["mce"]) < 0.10)


def run_phase15c() -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    all_rows: list[dict[str, Any]] = []
    for phase, phase_dir in PHASES:
        for regime in REGIMES:
            df = load_dataset(phase_dir, regime)
            if df is None or df.empty:
                print(f"skip {phase}/{regime}: no dataset", flush=True)
                continue
            feats = feature_cols_for(phase_dir, df)
            if len(feats) < 5:
                print(f"skip {phase}/{regime}: few features", flush=True)
                continue
            for model_type in ("lightgbm", "xgboost", "random_forest"):
                print(
                    f"rebuild {phase}/{regime}/{model_type} n={len(df)} feats={len(feats)}",
                    flush=True,
                )
                try:
                    rows = evaluate_rebuild(
                        phase=phase,
                        regime=regime,
                        model_type=model_type,
                        df=df,
                        feature_cols=feats,
                    )
                    all_rows.extend(rows)
                except Exception as exc:
                    print(f"  FAIL {phase}/{regime}/{model_type}: {exc}", flush=True)

    if not all_rows:
        raise RuntimeError("No calibration evaluations produced")

    res = pd.DataFrame(all_rows)
    cal_only = res[res["method"] != "raw"].copy()
    # Prefer adequate holdouts for institutional ranking
    ranked = cal_only[cal_only["n_test"] >= MIN_TEST_FOR_BEST].copy()
    if ranked.empty:
        ranked = cal_only.copy()
    ranked = ranked.sort_values(["brier", "ece", "mce"]).reset_index(drop=True)

    by_method = (
        ranked.groupby("method")[["brier", "ece", "mce"]]
        .mean()
        .sort_values(["brier", "ece", "mce"])
    )
    best_method_agg = str(by_method.index[0])
    best_agg = by_method.iloc[0]
    method_rows = ranked[ranked["method"] == best_method_agg].sort_values(
        ["brier", "ece", "mce"]
    )
    best_for_method = method_rows.iloc[0]

    any_cert = bool(ranked.apply(certified_row, axis=1).any())
    agg_cert = bool(
        float(best_agg["brier"]) < 0.12
        and float(best_agg["ece"]) < 0.05
        and float(best_agg["mce"]) < 0.10
    )
    # Certify only if best calibrator's best adequate-holdout row meets all gates
    ml_certified = bool(certified_row(best_for_method)) and any_cert

    regime_lines: list[str] = []
    for regime in REGIMES:
        sub = ranked[ranked["regime"] == regime]
        if sub.empty:
            regime_lines.append(f"  {regime}: NO_DATA (or n_test<{MIN_TEST_FOR_BEST})")
            continue
        g = sub.groupby("method")[["brier", "ece", "mce"]].mean().sort_values(["brier", "ece", "mce"])
        top_m = str(g.index[0])
        top = g.iloc[0]
        best_row = sub[sub["method"] == top_m].sort_values(["brier", "ece", "mce"]).iloc[0]
        cert = "YES" if certified_row(best_row) else "NO"
        regime_lines.append(
            f"  {regime}: best_method={top_m} mean_brier={top['brier']:.4f} "
            f"mean_ece={top['ece']:.4f} mean_mce={top['mce']:.4f} "
            f"best_model={best_row['phase']}/{best_row['model_type']} "
            f"brier={best_row['brier']:.4f} ece={best_row['ece']:.4f} mce={best_row['mce']:.4f} "
            f"n_test={int(best_row['n_test'])} CERT={cert}"
        )

    best_calibrator = best_method_agg
    best_brier = float(best_for_method["brier"])
    best_ece = float(best_for_method["ece"])
    best_mce = float(best_for_method["mce"])

    raw_mean = res[res["method"] == "raw"][["brier", "ece", "mce"]].mean()

    lines = [
        "PHASE 15C Institutional Calibration Hardening (Research Only)",
        "SOURCE=Phase11A + Phase13D datasets (models rebuilt train-only; no live changes)",
        "PIPELINE=chrono 60/20/20 train -> calib -> test",
        "METHODS=raw, platt, isotonic, temperature",
        f"MIN_TEST_FOR_BEST={MIN_TEST_FOR_BEST}",
        "PATCH_APPLIED=NO",
        f"EVALUATIONS={len(res)}",
        "",
        "=== Mean metrics by calibrator (excl. raw, n_test>=min) ===",
    ]
    for method, row in by_method.iterrows():
        lines.append(
            f"  {method:12s} Brier={row['brier']:.4f} ECE={row['ece']:.4f} MCE={row['mce']:.4f}"
        )

    lines.append("")
    lines.append("=== Raw baseline (mean, all evals) ===")
    lines.append(
        f"  raw          Brier={raw_mean['brier']:.4f} ECE={raw_mean['ece']:.4f} MCE={raw_mean['mce']:.4f}"
    )

    lines.append("")
    lines.append("=== Per regime ===")
    lines.extend(regime_lines)

    lines.append("")
    lines.append("=== Top 15 calibrated results (by Brier, adequate n_test) ===")
    for i, (_, r) in enumerate(ranked.head(15).iterrows(), start=1):
        lines.append(
            f"  {i:02d}. {r['phase']}/{r['regime']}/{r['model_type']}/{r['method']} "
            f"Brier={r['brier']:.4f} ECE={r['ece']:.4f} MCE={r['mce']:.4f} n_test={int(r['n_test'])}"
        )

    lines.append("")
    lines.append("CERTIFICATION_TARGETS: Brier<0.12 ECE<0.05 MCE<0.10")
    lines.append(f"ANY_ADEQUATE_HOLDOUT_CERTIFIED={'YES' if any_cert else 'NO'}")
    lines.append(f"AGG_METHOD_MEAN_CERTIFIED={'YES' if agg_cert else 'NO'}")
    lines.append("")
    lines.append("PHASE_15C_RESULT")
    lines.append(f"BEST_CALIBRATOR={best_calibrator}")
    lines.append(f"BEST_BRIER={round(best_brier, 6)}")
    lines.append(f"BEST_ECE={round(best_ece, 6)}")
    lines.append(f"BEST_MCE={round(best_mce, 6)}")
    lines.append(f"ML_CERTIFIED={'YES' if ml_certified else 'NO'}")
    lines.append(
        f"BEST_DETAIL={best_for_method['phase']}/{best_for_method['regime']}/"
        f"{best_for_method['model_type']}"
    )

    text = "\n".join(lines) + "\n"
    out = ROOT / "logs" / "phase15c_calibration_report.txt"
    out.write_text(text, encoding="utf-8")
    payload = {
        "by_method": {m: by_method.loc[m].to_dict() for m in by_method.index},
        "rows": all_rows,
        "best_calibrator": best_calibrator,
        "best_brier": best_brier,
        "best_ece": best_ece,
        "best_mce": best_mce,
        "ml_certified": ml_certified,
        "best_detail": {
            "phase": str(best_for_method["phase"]),
            "regime": str(best_for_method["regime"]),
            "model_type": str(best_for_method["model_type"]),
            "method": str(best_for_method["method"]),
            "n_test": int(best_for_method["n_test"]),
        },
        "pipeline": "chrono_60_20_20_rebuild",
    }
    (ROOT / "logs" / "phase15c_calibration_report.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    res.to_csv(ROOT / "logs" / "phase15c_calibration_matrix.csv", index=False)
    print(text)
    print("WROTE", out)
    return payload


if __name__ == "__main__":
    raise SystemExit(0 if run_phase15c() else 1)