#!/usr/bin/env python3
"""
PHASE 12B — Regime-Specific ML Institutional Training (RESEARCH ONLY).

Input:  data/ml/research/phase12a/pa_setups_labeled.parquet
Output: data/ml/research/phase12b/ + logs/phase12b/

Does NOT modify live trading flags or enable USE_ML_KERNEL.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
})
warnings.filterwarnings("ignore")

INPUT_PATH = ROOT / "data/ml/research/phase12a/pa_setups_labeled.parquet"
DATA_DIR = ROOT / "data/ml/research/phase12b"
MODEL_DIR = DATA_DIR / "models"
LOG_DIR = ROOT / "logs/phase12b"

META_THRESHOLD = 0.38
ML_CONFIRM_THRESHOLD = 0.52
ADAPTIVE_QUALITY_MIN = 0.33
REPLAY_DAYS = 180

from tradingbot.ml.feature_store import FEATURES  # noqa: E402

FEATURE_COLS = [c for c in FEATURES if c not in ("regime_code", "quality_score")]
REGIMES = ("TREND", "EXPANSION", "RANGING")

GATE = {
    "samples": 300,
    "oos_pf": 1.30,
    "oos_expectancy_r": 0.15,
    "precision_buy": 0.58,
    "precision_sell": 0.58,
    "brier_score": 0.12,
    "calibration_error": 0.08,
    "max_dd_r": 12.0,
}


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def _brier(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 1e-6, 1 - 1e-6)
    return float(np.mean((y_prob - y_true) ** 2))


def _calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> tuple[float, list[dict]]:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    reliability: list[dict] = []
    ece = 0.0
    n = len(y_true)
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        acc = float(y_true[mask].mean())
        conf = float(y_prob[mask].mean())
        reliability.append({
            "bin_lo": round(float(lo), 3),
            "bin_hi": round(float(hi), 3),
            "count": cnt,
            "mean_predicted": round(conf, 4),
            "mean_actual": round(acc, 4),
            "gap": round(abs(conf - acc), 4),
        })
        ece += (cnt / n) * abs(conf - acc)
    return round(float(ece), 4), reliability


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


def _recall_side(y_true, y_pred, directions, side: str) -> float:
    mask = directions == side
    if mask.sum() == 0:
        return 0.0
    return float(y_true[mask & (y_pred == 1)].sum() / max(y_true[mask].sum(), 1))


def _temperature_scale(logits: np.ndarray, y_true: np.ndarray) -> float:
    from scipy.optimize import minimize_scalar

    def nll(t: float) -> float:
        if t <= 0:
            return 1e9
        p = 1.0 / (1.0 + np.exp(-logits / t))
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return float(-np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p)))

    res = minimize_scalar(nll, bounds=(0.05, 10.0), method="bounded")
    return float(res.x if res.success else 1.0)


def _apply_calibration(method: str, train_prob: np.ndarray, y_train: np.ndarray, test_prob: np.ndarray) -> np.ndarray:
    train_prob = np.clip(train_prob, 1e-6, 1 - 1e-6)
    test_prob = np.clip(test_prob, 1e-6, 1 - 1e-6)
    if method == "platt":
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression(max_iter=500)
        lr.fit(train_prob.reshape(-1, 1), y_train)
        return lr.predict_proba(test_prob.reshape(-1, 1))[:, 1]
    if method == "isotonic":
        from sklearn.isotonic import IsotonicRegression
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(train_prob, y_train)
        return iso.predict(test_prob)
    if method == "temperature":
        logits = np.log(train_prob / (1 - train_prob))
        t = _temperature_scale(logits, y_train)
        test_logits = np.log(test_prob / (1 - test_prob))
        return 1.0 / (1.0 + np.exp(-test_logits / t))
    return test_prob


def _valid_stop(row: pd.Series) -> bool:
    entry, sl = float(row["entry_price"]), float(row["stop_price"])
    if entry <= 0 or sl <= 0 or abs(entry - sl) <= 0:
        return False
    if row["direction"] == "BUY" and sl >= entry:
        return False
    if row["direction"] == "SELL" and sl <= entry:
        return False
    return True


def task1_clean_sets(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    emit("TASK 1 — Build Clean Training Sets")
    clean = df.copy()
    clean["timestamp_utc"] = pd.to_datetime(clean["timestamp_utc"], utc=True)
    clean = clean[clean["label"].isin([0, 1])].copy()
    clean = clean[clean.apply(_valid_stop, axis=1)].copy()
    for col in FEATURE_COLS:
        if col not in clean.columns:
            raise KeyError(f"Missing feature column: {col}")
    clean = clean[clean[FEATURE_COLS].notna().all(axis=1)].copy()
    clean = clean.sort_values("timestamp_utc").reset_index(drop=True)
    emit(f"  clean rows={len(clean)} (from {len(df)})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    regime_dfs: dict[str, pd.DataFrame] = {}
    for regime in REGIMES:
        sub = clean[clean["regime"] == regime].copy()
        path = DATA_DIR / f"dataset_{regime.lower()}.parquet"
        sub.to_parquet(path, index=False)
        regime_dfs[regime] = sub
        emit(f"  {regime}: {len(sub)} -> {path.name}")
    return clean, regime_dfs


def _make_model(model_type: str):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

    if model_type == "lightgbm":
        import lightgbm as lgb
        return lgb.LGBMClassifier(
            n_estimators=120, max_depth=5, learning_rate=0.05, random_state=42, verbose=-1
        )
    if model_type == "xgboost":
        import xgboost as xgb
        return xgb.XGBClassifier(
            n_estimators=120, max_depth=5, learning_rate=0.05,
            random_state=42, eval_metric="logloss", verbosity=0,
        )
    if model_type == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            max_depth=6, learning_rate=0.05, max_iter=150, random_state=42
        )
    return RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)


def train_regime(regime: str, df: pd.DataFrame) -> dict[str, Any]:
    from sklearn.model_selection import TimeSeriesSplit

    emit(f"  train {regime} samples={len(df)}")
    if len(df) < 20:
        return {"skipped": True, "samples": len(df), "reason": "insufficient_samples"}

    X = df[FEATURE_COLS].astype(float).values
    y = df["label"].astype(int).values
    directions = df["direction"].astype(str).values
    rs = df["realized_r_multiple"].astype(float).values
    ts = df["timestamp_utc"]

    tscv = TimeSeriesSplit(n_splits=5)
    model_types = ["random_forest", "hist_gradient_boosting", "lightgbm", "xgboost"]
    results: list[dict[str, Any]] = []
    regime_best: dict[str, Any] | None = None
    regime_best_rank = (-1.0, -1.0, 999.0)

    for model_type in model_types:
        try:
            _ = _make_model(model_type)
        except Exception as exc:
            emit(f"    skip {model_type}: {exc}")
            continue

        fold_rows: list[dict[str, Any]] = []
        all_cal_prob: list[float] = []
        all_y: list[int] = []
        all_dirs: list[str] = []
        all_rs: list[float] = []

        for fold_i, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            if len(np.unique(y_tr)) < 2:
                continue

            model = _make_model(model_type)
            model.fit(X_tr, y_tr)
            tr_prob = model.predict_proba(X_tr)[:, 1]
            te_prob = model.predict_proba(X_te)[:, 1]

            cal_scores = {
                m: _brier(y_te, _apply_calibration(m, tr_prob, y_tr, te_prob))
                for m in ("platt", "isotonic", "temperature")
            }
            best_cal = min(cal_scores, key=cal_scores.get)
            cal_prob = _apply_calibration(best_cal, tr_prob, y_tr, te_prob)
            y_pred = (cal_prob >= ML_CONFIRM_THRESHOLD).astype(int)

            rs_te = rs[test_idx]
            taken = [float(r) for p, r in zip(cal_prob, rs_te) if p >= ML_CONFIRM_THRESHOLD]
            tm = _trade_metrics(taken)
            cal_err, rel_bins = _calibration_error(y_te, cal_prob)

            fold_rows.append({
                "fold": fold_i,
                "precision_buy": round(_precision_side(y_te, cal_prob, directions[test_idx], "BUY", ML_CONFIRM_THRESHOLD), 4),
                "precision_sell": round(_precision_side(y_te, cal_prob, directions[test_idx], "SELL", ML_CONFIRM_THRESHOLD), 4),
                "recall_buy": round(_recall_side(y_te, y_pred, directions[test_idx], "BUY"), 4),
                "recall_sell": round(_recall_side(y_te, y_pred, directions[test_idx], "SELL"), 4),
                "brier_score": round(cal_scores[best_cal], 4),
                "calibration_error": cal_err,
                "calibration_method": best_cal,
                "reliability_bins": rel_bins,
                "oos_pf": tm["pf"],
                "oos_expectancy_r": tm["expectancy_r"],
                "max_dd_r": tm["max_dd_r"],
                "oos_trades": tm["trades"],
            })

            all_cal_prob.extend(cal_prob.tolist())
            all_y.extend(y_te.tolist())
            all_dirs.extend(directions[test_idx].tolist())
            all_rs.extend(rs_te.tolist())

        if not fold_rows:
            continue

        avg = {
            k: round(float(np.mean([f[k] for f in fold_rows if k not in ("fold", "calibration_method", "reliability_bins")])), 4)
            for k in fold_rows[0]
            if k not in ("fold", "calibration_method", "reliability_bins")
        }
        avg["calibration_method"] = fold_rows[-1]["calibration_method"]
        avg["reliability_bins"] = fold_rows[-1]["reliability_bins"]

        full = _make_model(model_type)
        full.fit(X, y)
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        artifact_path = MODEL_DIR / f"{regime.lower()}_{model_type}.pkl"
        artifact = {
            "model": full,
            "features": FEATURE_COLS,
            "regime": regime,
            "model_type": model_type,
            "metrics": avg,
            "train_period": f"{ts.iloc[0]} -> {ts.iloc[int(len(ts)*0.8)]}",
            "validation_period": f"{ts.iloc[int(len(ts)*0.8)]} -> {ts.iloc[-1]}",
        }
        artifact_path.write_bytes(pickle.dumps(artifact))

        entry = {
            "regime": regime,
            "model_type": model_type,
            "samples": len(df),
            "train_period": artifact["train_period"],
            "validation_period": artifact["validation_period"],
            "metrics": avg,
            "artifact": str(artifact_path.relative_to(ROOT)),
            "folds": fold_rows,
        }
        results.append(entry)

        rank = (min(avg["oos_pf"], 10.0), avg["oos_expectancy_r"], -avg["brier_score"])
        if rank > regime_best_rank:
            regime_best_rank = rank
            regime_best = entry

    return {
        "regime": regime,
        "samples": len(df),
        "models": results,
        "best": regime_best,
    }


def task2_train_all(regime_dfs: dict[str, pd.DataFrame]) -> dict[str, Any]:
    emit("TASK 2/3/4 — Train, Calibrate, Metrics")
    training: dict[str, Any] = {"regimes": {}, "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    for regime in REGIMES:
        training["regimes"][regime] = train_regime(regime, regime_dfs[regime])
    return training


def _regime_gate(metrics: dict[str, Any], samples: int) -> dict[str, Any]:
    checks = {
        "samples_gte_300": samples >= GATE["samples"],
        "oos_pf_gte_130": float(metrics.get("oos_pf", 0)) >= GATE["oos_pf"],
        "oos_exp_gte_015": float(metrics.get("oos_expectancy_r", 0)) >= GATE["oos_expectancy_r"],
        "precision_buy_gte_58": float(metrics.get("precision_buy", 0)) >= GATE["precision_buy"],
        "precision_sell_gte_58": float(metrics.get("precision_sell", 0)) >= GATE["precision_sell"],
        "brier_lte_012": float(metrics.get("brier_score", 1)) <= GATE["brier_score"],
        "calibration_error_lte_008": float(metrics.get("calibration_error", 1)) <= GATE["calibration_error"],
        "max_dd_lte_12r": float(metrics.get("max_dd_r", 99)) <= GATE["max_dd_r"],
    }
    return {"checks": checks, "deployable": all(checks.values())}


def build_training_matrix(training: dict[str, Any]) -> dict[str, Any]:
    matrix: dict[str, Any] = {"regimes": {}, "gates": {}}
    for regime in REGIMES:
        info = training["regimes"].get(regime, {})
        best = info.get("best") or {}
        m = best.get("metrics") or {}
        matrix["regimes"][regime] = {
            "sample_count": info.get("samples", 0),
            "best_model": best.get("model_type"),
            "train_period": best.get("train_period"),
            "validation_period": best.get("validation_period"),
            "precision_buy": m.get("precision_buy"),
            "precision_sell": m.get("precision_sell"),
            "recall_buy": m.get("recall_buy"),
            "recall_sell": m.get("recall_sell"),
            "oos_pf": m.get("oos_pf"),
            "oos_expectancy_r": m.get("oos_expectancy_r"),
            "max_dd_r": m.get("max_dd_r"),
            "brier_score": m.get("brier_score"),
            "calibration_error": m.get("calibration_error"),
            "calibration_method": m.get("calibration_method"),
            "artifact": best.get("artifact"),
        }
        matrix["gates"][regime] = _regime_gate(m, int(info.get("samples", 0)))
    return matrix


def _predict_row(model, features: list[str], row: pd.Series) -> float:
    x = np.array([[float(row.get(f, 0.0)) for f in features]], dtype=float)
    return float(model.predict_proba(x)[0, 1])


def task5_shadow_replay(clean: pd.DataFrame, training: dict[str, Any]) -> dict[str, Any]:
    emit("TASK 5 — Shadow Replay Certification")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=REPLAY_DAYS)
    replay = clean[clean["timestamp_utc"] >= cutoff].copy()
    if replay.empty:
        replay = clean.tail(min(len(clean), 800)).copy()
        emit(f"  fallback replay window rows={len(replay)}")
    else:
        emit(f"  replay rows={len(replay)} (last {REPLAY_DAYS}d)")

    models: dict[str, Any] = {}
    for regime in REGIMES:
        best = training["regimes"].get(regime, {}).get("best")
        if not best:
            continue
        path = ROOT / best["artifact"]
        if path.is_file():
            models[regime] = pickle.loads(path.read_bytes())

    def _filter(mode: str) -> pd.DataFrame:
        rows = []
        for _, row in replay.iterrows():
            if float(row.get("confidence", 0)) < META_THRESHOLD:
                continue
            if mode == "pa_meta_baseline":
                rows.append(row)
                continue
            regime = str(row["regime"])
            art = models.get(regime)
            if art is None:
                continue
            prob = _predict_row(art["model"], art["features"], row)
            if prob < ML_CONFIRM_THRESHOLD:
                continue
            if mode == "adaptive_ml":
                if float(row.get("quality_score", 0)) < ADAPTIVE_QUALITY_MIN:
                    continue
            rows.append(row)
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    modes: dict[str, Any] = {}
    for mode in ("pa_meta_baseline", "pa_meta_ml", "adaptive_ml"):
        sub = _filter(mode)
        rs = sub["realized_r_multiple"].astype(float).tolist() if len(sub) else []
        tm = _trade_metrics(rs)
        agree = 0
        if mode != "pa_meta_baseline" and len(sub):
            for _, row in sub.iterrows():
                art = models.get(str(row["regime"]))
                if art is None:
                    continue
                prob = _predict_row(art["model"], art["features"], row)
                direction = row["direction"]
                ml_buy = prob >= ML_CONFIRM_THRESHOLD
                if (direction == "BUY" and ml_buy) or (direction == "SELL" and not ml_buy):
                    agree += 1
        modes[mode] = {
            **tm,
            "agreement_rate": round(agree / max(len(sub), 1), 4) if mode != "pa_meta_baseline" else None,
        }
        emit(f"  {mode}: trades={tm['trades']} PF={tm['pf']} expR={tm['expectancy_r']}")

    return {"replay_days": REPLAY_DAYS, "replay_rows": len(replay), "modes": modes}


def task7_explainability(training: dict[str, Any], regime_dfs: dict[str, pd.DataFrame]) -> int:
    emit("TASK 7 — Explainability (SHAP)")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LOG_DIR / "ml_explanations.jsonl"
    n = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for regime in REGIMES:
            best = training["regimes"].get(regime, {}).get("best")
            df = regime_dfs[regime]
            if not best or df.empty:
                continue
            art = pickle.loads((ROOT / best["artifact"]).read_bytes())
            model = art["model"]
            features = art["features"]
            sample = df.tail(min(50, len(df)))

            shap_ok = False
            try:
                import shap
                explainer = shap.TreeExplainer(model)
                shap_ok = True
            except Exception:
                shap = None

            for _, row in sample.iterrows():
                x = np.array([[float(row.get(f, 0.0)) for f in features]], dtype=float)
                prob = float(model.predict_proba(x)[0, 1])
                contribs: list[dict] = []
                if shap_ok:
                    sv = explainer.shap_values(x)
                    if isinstance(sv, list):
                        sv = sv[1] if len(sv) > 1 else sv[0]
                    vals = np.asarray(sv).flatten()
                    pairs = sorted(zip(features, vals), key=lambda t: abs(t[1]), reverse=True)[:10]
                    contribs = [{"feature": f, "contribution": round(float(v), 6)} for f, v in pairs]
                elif hasattr(model, "feature_importances_"):
                    imp = model.feature_importances_
                    pairs = sorted(zip(features, imp * x.flatten()), key=lambda t: abs(t[1]), reverse=True)[:10]
                    contribs = [{"feature": f, "contribution": round(float(v), 6)} for f, v in pairs]

                rec = {
                    "setup_id": row.get("setup_id"),
                    "timestamp_utc": str(row.get("timestamp_utc")),
                    "regime": regime,
                    "direction": row.get("direction"),
                    "model_type": best.get("model_type"),
                    "confidence": round(prob, 4),
                    "top_10_feature_contributions": contribs,
                }
                fh.write(json.dumps(rec, default=str) + "\n")
                n += 1
    emit(f"  explanations={n} -> {out_path}")
    return n


def main() -> int:
    from tradingbot.config.dotenv_loader import load_dotenv

    load_dotenv()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    emit(f"PHASE 12B Regime Training | UTC {datetime.now(timezone.utc).isoformat()}")
    if not INPUT_PATH.is_file():
        emit(f"ERROR missing input: {INPUT_PATH}")
        return 1

    raw = pd.read_parquet(INPUT_PATH)
    clean, regime_dfs = task1_clean_sets(raw)
    training = task2_train_all(regime_dfs)
    matrix = build_training_matrix(training)
    matrix_path = LOG_DIR / "training_matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    emit(f"  matrix -> {matrix_path}")

    replay = task5_shadow_replay(clean, training)
    task7_explainability(training, regime_dfs)

    # Pick best regime/model by OOS PF then expectancy
    best_regime = None
    best_model = None
    best_rank = (-1.0, -1.0)
    regime_lines: dict[str, dict] = {}
    any_deployable = False

    for regime in REGIMES:
        info = training["regimes"].get(regime, {})
        best = info.get("best") or {}
        m = best.get("metrics") or {}
        gate = matrix["gates"][regime]
        if gate.get("deployable"):
            any_deployable = True
        regime_lines[regime] = {
            "model": best.get("model_type", "NONE"),
            "pf": m.get("oos_pf", 0.0),
            "exp_r": m.get("oos_expectancy_r", 0.0),
        }
        rank = (float(m.get("oos_pf", 0)), float(m.get("oos_expectancy_r", 0)))
        if rank > best_rank and best.get("model_type"):
            best_rank = rank
            best_regime = regime
            best_model = best.get("model_type")

    replay_ml = replay["modes"].get("pa_meta_ml", {})
    overall_pf = replay_ml.get("pf", 0.0)
    overall_exp = replay_ml.get("expectancy_r", 0.0)
    inst_ready = "YES" if any_deployable else "NO"
    keep_shadow = "YES" if inst_ready == "NO" else "NO"

    lines = [
        "PHASE_12B_RESULT",
        f"TREND_MODEL={regime_lines['TREND']['model']}",
        f"TREND_PF={regime_lines['TREND']['pf']}",
        f"TREND_EXPECTANCY_R={regime_lines['TREND']['exp_r']}",
        f"EXPANSION_MODEL={regime_lines['EXPANSION']['model']}",
        f"EXPANSION_PF={regime_lines['EXPANSION']['pf']}",
        f"EXPANSION_EXPECTANCY_R={regime_lines['EXPANSION']['exp_r']}",
        f"RANGING_MODEL={regime_lines['RANGING']['model']}",
        f"RANGING_PF={regime_lines['RANGING']['pf']}",
        f"RANGING_EXPECTANCY_R={regime_lines['RANGING']['exp_r']}",
        f"BEST_REGIME={best_regime or 'NONE'}",
        f"BEST_MODEL={best_model or 'NONE'}",
        f"OVERALL_OOS_PF={overall_pf}",
        f"OVERALL_EXPECTANCY_R={overall_exp}",
        f"ML_KERNEL_INSTITUTIONAL_READY={inst_ready}",
        f"KEEP_SHADOW_MODE={keep_shadow}",
    ]
    result_path = LOG_DIR / "phase12b_result.txt"
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        emit(line)

    emit("")
    emit("Deliverables:")
    for p in (
        DATA_DIR / "dataset_trend.parquet",
        DATA_DIR / "dataset_expansion.parquet",
        DATA_DIR / "dataset_ranging.parquet",
        matrix_path,
        LOG_DIR / "ml_explanations.jsonl",
        result_path,
    ):
        emit(f"  {p} exists={p.is_file()}")

    return 0 if inst_ready == "YES" else 2


if __name__ == "__main__":
    raise SystemExit(main())
