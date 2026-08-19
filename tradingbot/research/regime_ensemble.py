"""PHASE 16C — Regime-Aware ML Ensemble (research only).

PurgedKFold + embargo, per-regime LightGBM/XGBoost/RF, PF-weighted voting.
NO live ML enable / NO USE_ML_KERNEL changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, precision_score, recall_score

FEATURE_COLS = [
    "atr_pct",
    "atr_percentile_20",
    "atr_percentile_50",
    "ema20_50_sep_pct",
    "h1_trend",
    "h4_trend",
    "session_london",
    "session_ny",
    "session_overlap",
    "spread_pips",
    "spread_regime",
    "tick_volume_ratio",
    "previous_bar_range",
    "sweep_high",
    "sweep_low",
    "bos_distance_atr",
    "fvg_size_atr",
    "candle_body_pct",
    "wick_upper_pct",
    "wick_lower_pct",
    "hour_sin",
    "hour_cos",
    "weekday",
    "regime_code",
    "quality_score",
]

MODEL_TYPES = ("lightgbm", "xgboost", "random_forest")
REGIMES = ("TREND", "EXPANSION", "RANGING")
DECISION_THRESHOLD = 0.52


@dataclass
class ModelOOFResult:
    regime: str
    model_type: str
    oof_prob: np.ndarray
    oof_idx: np.ndarray
    metrics: dict[str, float]
    calibration_method: str
    weight: float = 0.0


class PurgedKFold:
    """Chronological K-fold with purge gap + embargo (Lopez de Prado style)."""

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01):
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(self, n: int) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        if n < self.n_splits * 10:
            # fallback tiny
            cut = max(1, int(n * 0.7))
            yield np.arange(0, cut), np.arange(cut, n)
            return
        indices = np.arange(n)
        fold_sizes = np.full(self.n_splits, n // self.n_splits, dtype=int)
        fold_sizes[: n % self.n_splits] += 1
        embargo = max(1, int(n * self.embargo_pct))
        current = 0
        folds = []
        for fs in fold_sizes:
            folds.append((current, current + fs))
            current += fs
        for te_start, te_end in folds:
            # purge one fold-width before test (approx event horizon) + embargo after
            purge = max(embargo, (te_end - te_start) // 4)
            train_mask = np.ones(n, dtype=bool)
            # remove test
            train_mask[te_start:te_end] = False
            # purge before test
            p0 = max(0, te_start - purge)
            train_mask[p0:te_start] = False
            # embargo after test
            e1 = min(n, te_end + embargo)
            train_mask[te_end:e1] = False
            tr = indices[train_mask]
            te = indices[te_start:te_end]
            if len(tr) < 20 or len(te) < 5:
                continue
            yield tr, te


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


def ece_mce(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> tuple[float, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = mce = 0.0
    n = len(y_true)
    if n == 0:
        return 1.0, 1.0
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (y_prob >= lo) & (y_prob < hi if i < n_bins - 1 else y_prob <= hi)
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        gap = abs(float(y_true[mask].mean()) - float(y_prob[mask].mean()))
        ece += (cnt / n) * gap
        mce = max(mce, gap)
    return round(float(ece), 6), round(float(mce), 6)


def psi_histogram(expected: np.ndarray, actual: np.ndarray, n_bins: int = 10) -> float:
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[np.isfinite(expected)]
    actual = actual[np.isfinite(actual)]
    if len(expected) < 5 or len(actual) < 5:
        return 0.0
    breaks = np.unique(np.percentile(expected, np.linspace(0, 100, n_bins + 1)))
    if len(breaks) < 3:
        return 0.0
    e_counts = np.histogram(expected, bins=breaks)[0].astype(float)
    a_counts = np.histogram(actual, bins=breaks)[0].astype(float)
    e_pct = (e_counts + 1e-6) / (e_counts.sum() + 1e-6 * len(e_counts))
    a_pct = (a_counts + 1e-6) / (a_counts.sum() + 1e-6 * len(a_counts))
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def mean_feature_psi(df: pd.DataFrame, feature_cols: list[str], train_idx: np.ndarray, test_idx: np.ndarray) -> float:
    vals = []
    for c in feature_cols:
        if c not in df.columns:
            continue
        vals.append(
            psi_histogram(
                df.iloc[train_idx][c].astype(float).values,
                df.iloc[test_idx][c].astype(float).values,
            )
        )
    return float(np.mean(vals)) if vals else 0.0


def trade_metrics(rs: list[float]) -> dict[str, float]:
    if not rs:
        return {"oos_pf": 0.0, "oos_expectancy_r": 0.0, "trades": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    if gl > 0:
        pf = gw / gl
    elif gw > 0:
        # no losses: cap by sample size to avoid infinite PF dominating ranks
        pf = min(10.0, 1.0 + gw) if len(rs) >= 5 else 0.0
    else:
        pf = 0.0
    return {
        "oos_pf": round(min(pf, 99.0), 4),
        "oos_expectancy_r": round(sum(rs) / len(rs), 4),
        "trades": len(rs),
    }


def calibrate_oof(
    raw_oof: np.ndarray, y: np.ndarray, method: str
) -> tuple[np.ndarray, Any]:
    raw_oof = np.clip(raw_oof, 1e-6, 1 - 1e-6)
    if method == "isotonic":
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_oof, y)
        return np.asarray(iso.predict(raw_oof), dtype=float), iso
    lr = LogisticRegression(max_iter=1000)
    lr.fit(raw_oof.reshape(-1, 1), y)
    return lr.predict_proba(raw_oof.reshape(-1, 1))[:, 1], lr


def apply_calibrator(calibrator: Any, method: str, probs: np.ndarray) -> np.ndarray:
    probs = np.clip(probs, 1e-6, 1 - 1e-6)
    if method == "isotonic":
        return np.asarray(calibrator.predict(probs), dtype=float)
    return calibrator.predict_proba(probs.reshape(-1, 1))[:, 1]


def ensemble_weight(pf: float, brier: float) -> float:
    return float(max(pf - 1.0, 0.0) * max(1.0 - brier, 0.0))


def train_regime_models(
    regime: str,
    df: pd.DataFrame,
    *,
    feature_cols: list[str] | None = None,
    n_splits: int = 5,
    embargo_pct: float = 0.01,
) -> dict[str, Any]:
    feature_cols = feature_cols or FEATURE_COLS
    work = df[df["label"].isin([0, 1])].copy().reset_index(drop=True)
    work["timestamp_utc"] = pd.to_datetime(work["timestamp_utc"], utc=True, format="mixed")
    work = work.sort_values("timestamp_utc").reset_index(drop=True)

    X = work[feature_cols].astype(float).values
    y = work["label"].astype(int).values
    directions = work["direction"].astype(str).str.upper().values
    rs = work["realized_r_multiple"].astype(float).values

    pkf = PurgedKFold(n_splits=n_splits, embargo_pct=embargo_pct)
    model_results: list[dict[str, Any]] = []
    fitted_models: dict[str, Any] = {}

    for model_type in MODEL_TYPES:
        oof_prob = np.full(len(work), np.nan)
        fold_pfs = []
        psi_vals = []
        n_oof = 0
        for tr, te in pkf.split(len(work)):
            if len(np.unique(y[tr])) < 2:
                continue
            model = make_model(model_type, y[tr])
            model.fit(X[tr], y[tr])
            raw_te = model.predict_proba(X[te])[:, 1]
            # store RAW OOF; calibrate once after all folds
            oof_prob[te] = raw_te
            n_oof += len(te)
            taken = [float(rs[j]) for j, p in zip(te, raw_te) if p >= DECISION_THRESHOLD]
            fold_pfs.append(trade_metrics(taken)["oos_pf"])
            psi_vals.append(mean_feature_psi(work, feature_cols, tr, te))

        mask = np.isfinite(oof_prob)
        if mask.sum() < 20:
            continue
        y_o = y[mask]
        p_o = oof_prob[mask]
        d_o = directions[mask]
        r_o = rs[mask]

        # final calibration method by OOF sample count
        final_method = "isotonic" if int(mask.sum()) >= 300 else "platt"
        try:
            p_cal, calibrator = calibrate_oof(p_o, y_o, final_method)
        except Exception:
            p_cal, calibrator = p_o, None
            final_method = "none"

        brier = float(brier_score_loss(y_o, np.clip(p_cal, 0, 1)))
        ece, mce = ece_mce(y_o, p_cal)
        taken = [float(r) for p, r in zip(p_cal, r_o) if p >= DECISION_THRESHOLD]
        tm = trade_metrics(taken)

        # precision buy/sell
        buy_mask = (d_o == "BUY") | (d_o == "1") | (d_o == "LONG")
        sell_mask = (d_o == "SELL") | (d_o == "-1") | (d_o == "SHORT")
        # direction may be BUY/SELL strings from phase13d
        if not buy_mask.any() and not sell_mask.any():
            # numeric
            buy_mask = np.array([str(d) in ("1", "BUY", "buy") or d == 1 for d in d_o])
            sell_mask = np.array([str(d) in ("-1", "SELL", "sell") or d == -1 for d in d_o])

        def side_precision(side_mask):
            pred = (p_cal >= DECISION_THRESHOLD) & side_mask
            if pred.sum() == 0:
                return 0.0
            return float(y_o[pred].mean())

        prec_buy = side_precision(buy_mask)
        prec_sell = side_precision(sell_mask)
        y_hat = (p_cal >= DECISION_THRESHOLD).astype(int)
        try:
            recall = float(recall_score(y_o, y_hat, zero_division=0))
        except Exception:
            recall = 0.0

        metrics = {
            "oos_pf": tm["oos_pf"],
            "oos_expectancy_r": tm["oos_expectancy_r"],
            "precision_buy": round(prec_buy, 4),
            "precision_sell": round(prec_sell, 4),
            "recall": round(recall, 4),
            "brier": round(brier, 6),
            "ece": ece,
            "mce": mce,
            "psi_vs_train": round(float(np.mean(psi_vals)) if psi_vals else 0.0, 6),
            "oos_trades": tm["trades"],
            "oof_samples": int(mask.sum()),
            "fold_avg_pf": round(float(np.mean(fold_pfs)) if fold_pfs else 0.0, 4),
            "calibration_method": final_method,
        }
        w = ensemble_weight(metrics["oos_pf"], metrics["brier"])
        # fit full model for inference
        full = make_model(model_type, y)
        full.fit(X, y)
        fitted_models[model_type] = {
            "model": full,
            "calibrator": calibrator,
            "calibration_method": final_method,
            "weight": w,
            "metrics": metrics,
            "oof_prob": p_cal,
            "oof_mask": mask,
        }
        model_results.append({"model_type": model_type, "metrics": metrics, "weight": w})

    # normalize weights; fallback if all zero
    weights = {m: fitted_models[m]["weight"] for m in fitted_models}
    s = sum(weights.values())
    if s <= 1e-12:
        # fallback: (1-brier)
        for m in fitted_models:
            b = fitted_models[m]["metrics"]["brier"]
            weights[m] = max(1.0 - b, 1e-3)
            fitted_models[m]["weight"] = weights[m]
        s = sum(weights.values())
    for m in fitted_models:
        fitted_models[m]["weight"] = weights[m] / s
        for row in model_results:
            if row["model_type"] == m:
                row["weight"] = fitted_models[m]["weight"]

    best = None
    best_key = (-1e9, -1e9, -1e9, 1e9)
    for row in model_results:
        m = row["metrics"]
        # prefer models with enough OOS trades
        key = (1 if m.get("oos_trades", 0) >= 5 else 0, m["oos_pf"], m["oos_expectancy_r"], -m["brier"])
        if key > best_key:
            best_key = key
            best = row

    return {
        "regime": regime,
        "samples": len(work),
        "models": model_results,
        "best": best,
        "fitted": fitted_models,
        "feature_cols": feature_cols,
        "frame": work,
    }


def predict_ensemble(regime_pack: dict[str, Any], X: np.ndarray) -> np.ndarray:
    fitted = regime_pack["fitted"]
    if not fitted:
        return np.zeros(len(X))
    acc = np.zeros(len(X), dtype=float)
    for _mt, pack in fitted.items():
        raw = pack["model"].predict_proba(X)[:, 1]
        method = pack["calibration_method"]
        cal = pack["calibrator"]
        if cal is not None and method in ("platt", "isotonic"):
            p = apply_calibrator(cal, method, raw)
        else:
            p = raw
        acc += pack["weight"] * np.asarray(p, dtype=float)
    return acc


def predict_single(regime_pack: dict[str, Any], model_type: str, X: np.ndarray) -> np.ndarray:
    pack = regime_pack["fitted"][model_type]
    raw = pack["model"].predict_proba(X)[:, 1]
    method = pack["calibration_method"]
    cal = pack["calibrator"]
    if cal is not None and method in ("platt", "isotonic"):
        return apply_calibrator(cal, method, raw)
    return raw