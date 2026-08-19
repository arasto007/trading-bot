"""PHASE 18B PA meta retrain helpers (research only)."""
from __future__ import annotations

from typing import Any, Iterator

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import brier_score_loss
from sklearn.utils.class_weight import compute_sample_weight

from tradingbot.ml.feature_store import FEATURES
from tradingbot.research.calibration_hardening import (
    apply_isotonic,
    apply_platt,
    apply_temperature,
    ece_mce,
    fit_isotonic,
    fit_platt,
    fit_temperature,
)
from tradingbot.research.regime_ensemble import mean_feature_psi, trade_metrics

REGIMES = ("TREND", "EXPANSION", "RANGING")
MODEL_TYPES = ("lightgbm", "xgboost", "random_forest")
CALIBRATORS = ("platt", "isotonic", "temperature")
META_THRESHOLD = 0.38
GATES = {
    "oos_pf": 1.25,
    "oos_expectancy_r": 0.15,
    "precision_buy": 0.58,
    "precision_sell": 0.58,
    "brier": 0.12,
    "ece": 0.05,
    "psi": 0.25,
}
MIN_OOS_TRADES = 10


class PurgedKFoldBars:
    """Chronological K-fold with a fixed bar embargo (Lopez de Prado style)."""

    def __init__(self, n_splits: int = 5, embargo_bars: int = 3):
        self.n_splits = n_splits
        self.embargo_bars = int(embargo_bars)

    def split(self, bar_index: np.ndarray) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        n = len(bar_index)
        if n < self.n_splits * 8:
            cut = max(1, int(n * 0.7))
            yield np.arange(0, cut), np.arange(cut, n)
            return
        fold_sizes = np.full(self.n_splits, n // self.n_splits, dtype=int)
        fold_sizes[: n % self.n_splits] += 1
        current = 0
        folds: list[tuple[int, int]] = []
        for fs in fold_sizes:
            folds.append((current, current + fs))
            current += fs
        idx = np.arange(n)
        bars = np.asarray(bar_index, dtype=int)
        embargo = self.embargo_bars
        for te_start, te_end in folds:
            te = idx[te_start:te_end]
            te_bars = bars[te]
            lo = int(te_bars.min()) - embargo
            hi = int(te_bars.max()) + embargo
            train_mask = np.ones(n, dtype=bool)
            train_mask[te_start:te_end] = False
            train_mask &= ~((bars >= lo) & (bars <= hi))
            tr = idx[train_mask]
            if len(tr) < 20 or len(te) < 5:
                continue
            yield tr, te


def make_model(model_type: str):
    if model_type == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=140,
            max_depth=5,
            learning_rate=0.05,
            random_state=42,
            verbose=-1,
            class_weight="balanced",
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
        )
    return RandomForestClassifier(
        n_estimators=250,
        max_depth=6,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )


def fit_balanced(model, X: np.ndarray, y: np.ndarray):
    sw = compute_sample_weight("balanced", y)
    try:
        model.fit(X, y, sample_weight=sw)
    except TypeError:
        model.fit(X, y)
    return model


def honest_split(
    df: pd.DataFrame, *, embargo_bars: int = 3
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = df.sort_values("timestamp_utc").reset_index(drop=True)
    n = len(work)
    tr_end = int(n * 0.60)
    cal_end = int(n * 0.80)
    if n < 25:
        tr_end = max(8, int(n * 0.50))
        cal_end = max(tr_end + 4, int(n * 0.75))
        cal_end = min(cal_end, n - 4)
    train = work.iloc[:tr_end].copy()
    calib = work.iloc[tr_end:cal_end].copy()
    test = work.iloc[cal_end:].copy()
    if "bar_index" in work.columns and len(calib) and len(train):
        b0 = int(calib["bar_index"].iloc[0])
        train = train[train["bar_index"] < (b0 - embargo_bars)].copy()
    if "bar_index" in work.columns and len(test) and len(calib):
        b1 = int(test["bar_index"].iloc[0])
        calib = calib[calib["bar_index"] < (b1 - embargo_bars)].copy()
    return train.reset_index(drop=True), calib.reset_index(drop=True), test.reset_index(drop=True)


def apply_calibrator(method: str, pack: Any, probs: np.ndarray) -> np.ndarray:
    if method == "platt":
        return apply_platt(pack, probs)
    if method == "isotonic":
        return apply_isotonic(pack, probs)
    return apply_temperature(float(pack), probs)


def fit_calibrator(method: str, p_cal: np.ndarray, y_cal: np.ndarray) -> Any:
    if method == "platt":
        return fit_platt(p_cal, y_cal)
    if method == "isotonic":
        return fit_isotonic(p_cal, y_cal)
    return fit_temperature(p_cal, y_cal)


def side_precision(
    y: np.ndarray, p: np.ndarray, direction: np.ndarray, side: str, threshold: float
) -> float:
    d = np.asarray(direction).astype(str)
    if side == "BUY":
        mask = np.isin(d, ("BUY", "1", "LONG"))
    else:
        mask = np.isin(d, ("SELL", "-1", "SHORT"))
    pred = (p >= threshold) & mask
    if int(pred.sum()) == 0:
        return 0.0
    return float(np.asarray(y, dtype=float)[pred].mean())


def eval_test(
    *,
    y: np.ndarray,
    p: np.ndarray,
    direction: np.ndarray,
    realized_r: np.ndarray,
    psi: float,
    threshold: float = META_THRESHOLD,
) -> dict[str, Any]:
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    y = np.asarray(y, dtype=int)
    taken = [float(r) for prob, r in zip(p, realized_r) if prob >= threshold]
    tm = trade_metrics(taken)
    brier = float(brier_score_loss(y, p)) if len(y) else 1.0
    ece, mce = ece_mce(y, p) if len(y) else (1.0, 1.0)
    return {
        "oos_pf": tm["oos_pf"],
        "oos_expectancy_r": tm["oos_expectancy_r"],
        "oos_trades": tm["trades"],
        "precision_buy": round(side_precision(y, p, direction, "BUY", threshold), 4),
        "precision_sell": round(side_precision(y, p, direction, "SELL", threshold), 4),
        "brier": round(brier, 6),
        "ece": ece,
        "mce": mce,
        "psi": round(float(psi), 6),
        "n_test": int(len(y)),
        "pos_rate_test": round(float(y.mean()) if len(y) else 0.0, 4),
        "accept_rate": round(float((p >= threshold).mean()) if len(p) else 0.0, 4),
        "threshold": threshold,
    }


def gates_pass(m: dict[str, Any]) -> bool:
    if int(m.get("oos_trades") or 0) < MIN_OOS_TRADES:
        return False
    return (
        float(m["oos_pf"]) > GATES["oos_pf"]
        and float(m["oos_expectancy_r"]) > GATES["oos_expectancy_r"]
        and float(m["precision_buy"]) > GATES["precision_buy"]
        and float(m["precision_sell"]) > GATES["precision_sell"]
        and float(m["brier"]) < GATES["brier"]
        and float(m["ece"]) < GATES["ece"]
        and float(m["psi"]) < GATES["psi"]
    )


def cv_oof_on_train(
    model_type: str,
    train: pd.DataFrame,
    feature_cols: list[str],
    *,
    embargo_bars: int = 3,
) -> dict[str, Any]:
    X = train[feature_cols].astype(float).values
    y = train["label"].astype(int).values
    bars = (
        train["bar_index"].astype(int).values
        if "bar_index" in train.columns
        else np.arange(len(train))
    )
    oof = np.full(len(train), np.nan)
    n_folds = 0
    pkf = PurgedKFoldBars(n_splits=5, embargo_bars=embargo_bars)
    for tr, te in pkf.split(bars):
        if len(np.unique(y[tr])) < 2:
            continue
        model = make_model(model_type)
        fit_balanced(model, X[tr], y[tr])
        oof[te] = model.predict_proba(X[te])[:, 1]
        n_folds += 1
    mask = np.isfinite(oof)
    if mask.sum() < 10 or len(np.unique(y[mask])) < 2:
        return {"cv_folds": n_folds, "cv_brier": None, "cv_samples": int(mask.sum())}
    brier = float(brier_score_loss(y[mask], np.clip(oof[mask], 0, 1)))
    return {"cv_folds": n_folds, "cv_brier": round(brier, 6), "cv_samples": int(mask.sum())}


def train_regime(
    regime: str,
    df: pd.DataFrame,
    *,
    feature_cols: list[str] | None = None,
    embargo_bars: int = 3,
    threshold: float = META_THRESHOLD,
) -> dict[str, Any]:
    feature_cols = feature_cols or list(FEATURES)
    work = df[df["label"].isin([0, 1])].copy()
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True, format="mixed")
    work["direction"] = work["direction"].astype(str).str.upper()
    for c in feature_cols:
        if c not in work.columns:
            work[c] = 0.0
    work = work.replace([np.inf, -np.inf], np.nan)
    work[feature_cols] = work[feature_cols].fillna(0.0)
    work = work.sort_values("timestamp_utc").reset_index(drop=True)

    train, calib, test = honest_split(work, embargo_bars=embargo_bars)
    out: dict[str, Any] = {
        "regime": regime,
        "samples": int(len(work)),
        "n_train": int(len(train)),
        "n_calib": int(len(calib)),
        "n_test": int(len(test)),
        "models": [],
        "best": None,
    }
    if len(train) < 20 or len(calib) < 8 or len(test) < 8 or len(np.unique(train["label"])) < 2:
        out["skip"] = "insufficient_split"
        return out
    identity_cal = len(np.unique(calib["label"])) < 2
    if identity_cal:
        out["skip"] = "calib_single_class_identity_calibrators"

    X_tr = train[feature_cols].astype(float).values
    y_tr = train["label"].astype(int).values
    X_ca = calib[feature_cols].astype(float).values
    y_ca = calib["label"].astype(int).values
    X_te = test[feature_cols].astype(float).values
    y_te = test["label"].astype(int).values
    d_te = test["direction"].astype(str).values
    r_te = test["realized_r_multiple"].astype(float).values
    test_pos = np.arange(len(work) - len(test), len(work))
    train_pos = np.arange(len(train))
    psi = mean_feature_psi(work, feature_cols, train_pos, test_pos)

    best_row = None
    best_key = None
    for model_type in MODEL_TYPES:
        cv = cv_oof_on_train(model_type, train, feature_cols, embargo_bars=embargo_bars)
        model = make_model(model_type)
        fit_balanced(model, X_tr, y_tr)
        p_ca = np.asarray(model.predict_proba(X_ca)[:, 1], dtype=float)
        p_te_raw = np.asarray(model.predict_proba(X_te)[:, 1], dtype=float)
        model_entry: dict[str, Any] = {
            "model_type": model_type,
            "cv": cv,
            "calibrators": {},
        }
        for method in CALIBRATORS:
            try:
                if identity_cal:
                    p_te = p_te_raw
                else:
                    pack = fit_calibrator(method, p_ca, y_ca)
                    p_te = apply_calibrator(method, pack, p_te_raw)
            except Exception as exc:
                model_entry["calibrators"][method] = {"error": str(exc)}
                continue
            metrics = eval_test(
                y=y_te,
                p=p_te,
                direction=d_te,
                realized_r=r_te,
                psi=psi,
                threshold=threshold,
            )
            metrics["passed"] = gates_pass(metrics)
            model_entry["calibrators"][method] = metrics
            key = (
                1 if metrics["passed"] else 0,
                1 if metrics["oos_trades"] >= MIN_OOS_TRADES else 0,
                float(metrics["oos_pf"]),
                float(metrics["oos_expectancy_r"]),
                -float(metrics["brier"]),
                -float(metrics["ece"]),
            )
            if best_key is None or key > best_key:
                best_key = key
                best_row = {
                    "regime": regime,
                    "model_type": model_type,
                    "calibrator": method,
                    "metrics": metrics,
                }
        out["models"].append(model_entry)
    out["best"] = best_row
    return out

