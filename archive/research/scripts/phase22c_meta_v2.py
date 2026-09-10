#!/usr/bin/env python3
"""PHASE 22C model-specific Meta v2. Research only. No live patches."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import brier_score_loss, confusion_matrix
from sklearn.utils.class_weight import compute_sample_weight

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

from tradingbot.config.dotenv_loader import load_dotenv
load_dotenv()

from tradingbot.research.calibration_hardening import (
    apply_isotonic, apply_platt, ece_mce, fit_isotonic, fit_platt,
)
from tradingbot.research.pa_meta_retrain import PurgedKFoldBars
from tradingbot.research.regime_ensemble import mean_feature_psi, trade_metrics

OUT = ROOT / "logs" / "phase22c"
CERT_22B = ROOT / "logs" / "phase22b" / "certification_matrix.json"
CANDIDATE = "MODEL_B_SWEEP_MSS_FVG"
EMBARGO = 96
HORIZON = 96
MIN_PLATT = 20
MIN_ISOTONIC = 50
MIN_TEST = 30
MIN_TAKEN = 15
THRESH_GRID = (0.30, 0.35, 0.38, 0.40, 0.45, 0.50, 0.55, 0.60)
PRIOR_THRESH = 0.38
GATES = {
    "pf": 1.25, "exp_r": 0.15, "precision_buy": 0.58, "precision_sell": 0.58,
    "brier": 0.12, "ece": 0.05, "psi": 0.25,
}
FEATURE_COLS = [
    "model_id_code", "regime_code", "session_code", "dir_code",
    "sweep_quality", "sweep_depth_atr", "mss_strength", "displacement_strength",
    "fvg_size_atr", "distance_to_fvg", "pd_code", "htf_bias",
    "spread_pips", "atr_percentile", "planned_rr", "hour", "weekday",
    "hist_winrate", "hist_mfe", "hist_mae", "hist_n",
]
REGIME_CODE = {
    "RANGING": 0.0, "STRONG_TREND_UP": 1.0, "STRONG_TREND_DOWN": -1.0,
    "VOLATILE": 0.5, "CRISIS": -0.5,
}
SESSION_CODE = {"LONDON": 0.0, "NY": 1.0, "ASIAN": 2.0, "OVERLAP": 3.0}
PD_CODE = {"discount": -1.0, "equilibrium": 0.0, "premium": 1.0}


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_phase22a():
    path = ROOT / "scripts" / "phase22a_strategy_discovery.py"
    spec = importlib.util.spec_from_file_location("phase22a_strategy_discovery", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def certified_models_22b() -> list[str]:
    if not CERT_22B.is_file():
        return []
    blob = json.loads(CERT_22B.read_text(encoding="utf-8"))
    if blob.get("certified") is True:
        return [str(x) for x in (blob.get("candidates_from_22a") or [])]
    for line in str(blob.get("result_block") or "").splitlines():
        if line.startswith("CERTIFIED_MODELS="):
            val = line.split("=", 1)[1].strip()
            if val and val != "NONE":
                return [x.strip() for x in val.split(",") if x.strip()]
    return []


def collect_model_b(p22a):
    df = p22a.load_df()
    n = len(df)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)
    hours = np.array([int(ts.hour) for ts in df.index])
    dates = np.array([ts.date().isoformat() for ts in df.index])
    atr_pct = df["atr"].rolling(252, min_periods=20).rank(pct=True).to_numpy(dtype=float) * 100.0
    atr_pct = np.where(np.isnan(atr_pct), 50.0, atr_pct)
    regime = p22a.infer_regimes(df)
    swings = p22a.swing_arrays(high, low, n)
    pdh, pdl = p22a.last_completed_day_hl(dates, high, low, n)
    pwh, pwl = p22a.last_completed_week_hl(df.index, high, low, n)
    asian_hi, asian_lo = p22a.causal_range(dates, hours, high, low, n, 0, 8)
    lon_hi, lon_lo = p22a.causal_range(dates, hours, high, low, n, 7, 12)
    sess_hi, sess_lo = p22a.session_hl_arrays(dates, hours, n, asian_hi, asian_lo, lon_hi, lon_lo)
    htf_bias = p22a.htf_bias_array(df.index, close, n)
    ctx = {
        "n": n, "index": df.index, "hours": hours, "dates": dates,
        "high": high, "low": low, "close": close, "open": open_, "atr": atr,
        "atr_pct": atr_pct, "regime": regime, "swings": swings, "pdh": pdh,
        "pdl": pdl, "pwh": pwh, "pwl": pwl, "sess_hi": sess_hi, "sess_lo": sess_lo,
        "asian_hi": asian_hi, "asian_lo": asian_lo, "htf_bias": htf_bias,
    }
    raw, funnel = p22a.collect_structural(
        ctx, session=p22a.B_SESSION, use_htf_levels=False, require_pd=False
    )
    return df, ctx, raw, funnel

def add_causal_hist(rows: list[dict[str, Any]]) -> None:
    hist: list[dict[str, Any]] = []
    for r in rows:
        i = int(r["i"])
        closed = [h for h in hist if int(h["i"]) + HORIZON < i]
        last = closed[-20:]
        if last:
            r["hist_winrate"] = float(np.mean([h["win"] for h in last]))
            r["hist_mfe"] = float(np.mean([h["mfe"] for h in last]))
            r["hist_mae"] = float(np.mean([h["mae"] for h in last]))
            r["hist_n"] = float(len(last))
        else:
            r["hist_winrate"] = 0.5
            r["hist_mfe"] = 0.0
            r["hist_mae"] = 0.0
            r["hist_n"] = 0.0
        hist.append({
            "i": i,
            "win": 1.0 if float(r["final_R"]) > 0 else 0.0,
            "mfe": float(r.get("MFE_R") or 0.0),
            "mae": float(r.get("MAE_R") or 0.0),
        })


def rows_to_frame(rows: list[dict[str, Any]], ctx) -> pd.DataFrame:
    atr_pct = ctx["atr_pct"]
    index = ctx["index"]
    out = []
    for r in sorted(rows, key=lambda x: int(x["i"])):
        i = int(r["i"])
        rec = dict(r)
        rec["model_id"] = CANDIDATE
        rec["model_id_code"] = 1.0
        rec["regime_code"] = REGIME_CODE.get(str(r.get("regime") or ""), 0.0)
        rec["session_code"] = SESSION_CODE.get(str(r.get("session") or ""), 0.0)
        rec["dir_code"] = 1.0 if str(r.get("direction")) == "BUY" else -1.0
        rec["sweep_quality"] = float(min(max(float(r.get("sweep_depth_atr") or 0.0), 0.0), 3.0))
        rec["mss_strength"] = float(r.get("displacement_strength") or 0.0) if r.get("mss_choch_type") else 0.0
        rec["pd_code"] = PD_CODE.get(str(r.get("premium_discount") or "equilibrium"), 0.0)
        rec["atr_percentile"] = float(atr_pct[i])
        rec["weekday"] = float(index[i].weekday())
        rec["bar_index"] = i
        rec["timestamp_utc"] = r["timestamp"]
        rec["label"] = 1 if float(r["final_R"]) > 0 else 0
        rec["realized_r"] = float(r["final_R"])
        rec["spread_pips"] = float(r.get("spread_pips") or 0.0)
        rec["planned_rr"] = float(r.get("planned_rr") or 0.0)
        rec["hour"] = float(r.get("hour") or 0.0)
        rec["sweep_depth_atr"] = float(r.get("sweep_depth_atr") or 0.0)
        rec["displacement_strength"] = float(r.get("displacement_strength") or 0.0)
        rec["fvg_size_atr"] = float(r.get("fvg_size_atr") or 0.0)
        rec["distance_to_fvg"] = float(r.get("distance_to_fvg") or 0.0)
        rec["htf_bias"] = float(r.get("htf_bias") or 0.0)
        out.append(rec)
    add_causal_hist(out)
    df = pd.DataFrame(out)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, format="mixed")
    df = df.sort_values("bar_index").reset_index(drop=True)
    for c in FEATURE_COLS:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def honest_split(df: pd.DataFrame):
    work = df.sort_values("bar_index").reset_index(drop=True)
    n = len(work)
    tr_end = int(n * 0.60)
    cal_end = int(n * 0.80)
    train = work.iloc[:tr_end].copy()
    calib = work.iloc[tr_end:cal_end].copy()
    test = work.iloc[cal_end:].copy()
    if len(calib) and len(train):
        b0 = int(calib["bar_index"].iloc[0])
        train = train[train["bar_index"] < (b0 - EMBARGO)].copy()
    if len(test) and len(calib):
        b1 = int(test["bar_index"].iloc[0])
        calib = calib[calib["bar_index"] < (b1 - EMBARGO)].copy()
    return train.reset_index(drop=True), calib.reset_index(drop=True), test.reset_index(drop=True)


def fit_rf(X, y):
    model = RandomForestClassifier(
        n_estimators=250, max_depth=6, random_state=42, class_weight="balanced", n_jobs=-1,
    )
    sw = compute_sample_weight("balanced", y)
    model.fit(X, y, sample_weight=sw)
    return model


def purged_cv_brier(train: pd.DataFrame) -> dict[str, Any]:
    X = train[FEATURE_COLS].astype(float).values
    y = train["label"].astype(int).values
    bars = train["bar_index"].astype(int).values
    oof = np.full(len(train), np.nan)
    n_folds = 0
    pkf = PurgedKFoldBars(n_splits=5, embargo_bars=EMBARGO)
    for tr, te in pkf.split(bars):
        if len(np.unique(y[tr])) < 2:
            continue
        model = fit_rf(X[tr], y[tr])
        oof[te] = model.predict_proba(X[te])[:, 1]
        n_folds += 1
    mask = np.isfinite(oof)
    if mask.sum() < 10 or len(np.unique(y[mask])) < 2:
        return {"cv_folds": n_folds, "cv_brier": None, "cv_samples": int(mask.sum())}
    brier = float(brier_score_loss(y[mask], np.clip(oof[mask], 0, 1)))
    return {"cv_folds": n_folds, "cv_brier": round(brier, 6), "cv_samples": int(mask.sum())}


def side_precision(y, p, direction, side, th):
    d = np.asarray(direction).astype(str)
    mask = d == side
    pred = (np.asarray(p) >= th) & mask
    if int(pred.sum()) == 0:
        return 0.0
    return float(np.asarray(y, dtype=float)[pred].mean())


def eval_arm(rows_or_rs, *, y=None, p=None, direction=None, th=None, psi=None):
    if y is None:
        rs = [float(r) for r in rows_or_rs]
        tm = trade_metrics(rs)
        return {**tm, "precision_buy": None, "precision_sell": None, "brier": None, "ece": None, "mce": None, "psi": psi}
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    direction = np.asarray(direction).astype(str)
    realized = np.asarray(rows_or_rs, dtype=float)
    taken = [float(r) for prob, r in zip(p, realized) if prob >= th]
    tm = trade_metrics(taken)
    brier = float(brier_score_loss(y, p)) if len(y) else 1.0
    ece, mce = ece_mce(y, p) if len(y) else (1.0, 1.0)
    return {
        **tm,
        "precision_buy": round(side_precision(y, p, direction, "BUY", th), 4),
        "precision_sell": round(side_precision(y, p, direction, "SELL", th), 4),
        "brier": round(brier, 6),
        "ece": ece,
        "mce": mce,
        "psi": None if psi is None else round(float(psi), 6),
        "n_scored": int(len(y)),
        "accept_rate": round(float((p >= th).mean()) if len(p) else 0.0, 4),
        "threshold": th,
    }


def pick_threshold_on_calib(y, p, realized, direction):
    best = None
    best_key = None
    rows = []
    for th in THRESH_GRID:
        m = eval_arm(realized, y=y, p=p, direction=direction, th=th)
        rows.append({"threshold": th, **m})
        if int(m["trades"]) < 8:
            continue
        key = (float(m["oos_expectancy_r"]), float(m["oos_pf"]), -float(m["brier"]))
        if best_key is None or key > best_key:
            best_key = key
            best = th
    if best is None:
        best = PRIOR_THRESH
    return best, rows

def score_current_meta(frame: pd.DataFrame, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal
    from tradingbot.domain.trade_features import capture_entry_features
    from tradingbot.ml.features.unified_feature_store import FEATURES, to_vector
    from tradingbot.services.meta_labeler import MetaLabeler

    meta = MetaLabeler()
    info = {
        "ready_m5": bool(meta.is_ready_for("M5")),
        "n_scored": 0,
        "n_passthrough": 0,
        "base_threshold": PRIOR_THRESH,
    }
    model = meta._models.get("M5")
    names = list(meta._features.get("M5") or FEATURES)
    probs = np.ones(len(frame), dtype=float)
    ths = np.full(len(frame), PRIOR_THRESH, dtype=float)
    if model is None:
        info["error"] = "m5_model_missing"
        info["n_passthrough"] = int(len(frame))
        return probs, ths, info
    for k, rec in enumerate(frame.to_dict("records")):
        i = int(rec["bar_index"])
        start = max(0, i - 400)
        window = df.iloc[start : i + 1]
        direction = SignalDirection.BUY if str(rec.get("direction")) == "BUY" else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(min(max(float(rec.get("displacement_strength") or 0.5), 0.05), 1.0)),
            symbol="XAUUSD",
            timeframe="M5",
            strategy_name="london_sweep",
            stop_loss=float(rec.get("sl") or 0.0) or None,
            take_profit=float(rec.get("tp") or 0.0) or None,
            metadata={
                "setup": "liquidity_sweep",
                "rr": float(rec.get("planned_rr") or 0.0),
                "risk_reward_ratio": float(rec.get("planned_rr") or 0.0),
                "confidence": float(min(max(float(rec.get("displacement_strength") or 0.5), 0.05), 1.0)),
            },
        )
        snap = {
            "ohlcv": window,
            "current_time": df.index[i] if i < len(df.index) else rec.get("timestamp_utc"),
            "htf_bias": float(rec.get("htf_bias") or 0.0),
        }
        feats = capture_entry_features(
            sig, snap, str(rec.get("regime") or "RANGING"),
            spread_pips=float(rec.get("spread_pips") or 0.0),
            entry_price=float(rec.get("entry") or 0.0) or None,
        )
        if list(names) == list(FEATURES):
            row = to_vector(feats)
        else:
            row = [float(feats.get(name, 0.0)) for name in names]
        try:
            proba = model.predict_proba([row])[0]
            probs[k] = float(proba[1]) if len(proba) > 1 else float(proba[0])
            info["n_scored"] += 1
        except Exception:
            probs[k] = 1.0
            info["n_passthrough"] += 1
        ths[k] = float(meta.effective_threshold("M5", str(rec.get("regime") or "RANGING"), PRIOR_THRESH))
    return probs, ths, info


def calibration_curve(y, p, n_bins: int = 10):
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    curve = []
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (p >= lo) & (p < hi if i < n_bins - 1 else p <= hi)
        n = int(mask.sum())
        curve.append({
            "bin_lo": round(float(lo), 3),
            "bin_hi": round(float(hi), 3),
            "n": n,
            "mean_pred": None if n == 0 else round(float(p[mask].mean()), 4),
            "mean_actual": None if n == 0 else round(float(y[mask].mean()), 4),
        })
    return curve


def confusion(y, p, th):
    pred = (np.asarray(p) >= th).astype(int)
    y = np.asarray(y, dtype=int)
    if len(y) == 0:
        return {"tn": 0, "fp": 0, "fn": 0, "tp": 0}
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}


def gates_pass(m, *, trained_on_certified: bool, n_test: int) -> dict[str, bool]:
    g = {
        "trained_on_certified": trained_on_certified,
        "oos_sample_ge_30": int(n_test) >= MIN_TEST,
        "oos_taken_ge_15": int(m.get("trades") or 0) >= MIN_TAKEN,
        "pf_ge_1_25": float(m.get("oos_pf") or 0) >= GATES["pf"],
        "exp_gt_0_15": float(m.get("oos_expectancy_r") or 0) > GATES["exp_r"],
        "precision_buy_ge_58": float(m.get("precision_buy") or 0) >= GATES["precision_buy"],
        "precision_sell_ge_58": float(m.get("precision_sell") or 0) >= GATES["precision_sell"],
        "brier_lt_0_12": float(m.get("brier") or 1) < GATES["brier"],
        "ece_lt_0_05": float(m.get("ece") or 1) < GATES["ece"],
        "psi_lt_0_25": float(m.get("psi") or 1) < GATES["psi"],
    }
    return g

def apply_cd_rows(p22a, frame: pd.DataFrame) -> list[float]:
    rows = frame.to_dict("records")
    kept = p22a.apply_cd(rows)
    return [float(r["realized_r"]) for r in kept]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    certified = certified_models_22b()
    trained_on_certified = CANDIDATE in certified and len(certified) > 0
    emit("22B certified models=%s" % (certified or ["NONE"]))
    emit("TRAINED_ON_CERTIFIED=%s (diagnostic candidate=%s)" % (trained_on_certified, CANDIDATE))

    p22a = load_phase22a()
    emit("collect Model B setups only (no A/C mix) ...")
    df, ctx, raw, funnel = collect_model_b(p22a)
    emit("raw setups=%s funnel=%s" % (len(raw), funnel))
    frame = rows_to_frame(raw, ctx)
    emit("featured rows=%s pos_rate=%.3f" % (len(frame), float(frame["label"].mean()) if len(frame) else 0.0))

    train, calib, test = honest_split(frame)
    emit("split train=%s calib=%s test=%s" % (len(train), len(calib), len(test)))

    cv = {"cv_folds": 0, "cv_brier": None, "cv_samples": 0}
    cal_report: dict[str, Any] = {"platt": None, "isotonic": None, "chosen": None, "skipped": []}
    metav2_metrics = {
        "oos_pf": 0.0, "oos_expectancy_r": 0.0, "trades": 0,
        "precision_buy": 0.0, "precision_sell": 0.0, "brier": 1.0, "ece": 1.0, "mce": 1.0, "psi": 1.0,
        "n_scored": int(len(test)), "accept_rate": 0.0, "threshold": PRIOR_THRESH,
    }
    p_te = np.full(len(test), np.nan)
    chosen_method = None
    chosen_th = PRIOR_THRESH
    thresh_table = []
    psi = 1.0
    fit_ok = False

    can_fit = len(train) >= 40 and len(calib) >= MIN_PLATT and len(test) >= 8 and len(np.unique(train["label"])) >= 2
    if not can_fit:
        cal_report["skipped"].append("insufficient_split")
        emit("skip fit: insufficient split")
    else:
        X_tr = train[FEATURE_COLS].astype(float).values
        y_tr = train["label"].astype(int).values
        X_ca = calib[FEATURE_COLS].astype(float).values
        y_ca = calib["label"].astype(int).values
        X_te = test[FEATURE_COLS].astype(float).values
        y_te = test["label"].astype(int).values
        d_te = test["direction"].astype(str).values
        r_te = test["realized_r"].astype(float).values
        d_ca = calib["direction"].astype(str).values
        r_ca = calib["realized_r"].astype(float).values
        psi = mean_feature_psi(pd.concat([train, test], ignore_index=True), FEATURE_COLS, np.arange(len(train)), np.arange(len(train), len(train) + len(test)))
        emit("purged CV on train ...")
        cv = purged_cv_brier(train)
        emit("  cv=%s" % cv)
        model = fit_rf(X_tr, y_tr)
        p_ca_raw = np.asarray(model.predict_proba(X_ca)[:, 1], dtype=float)
        p_te_raw = np.asarray(model.predict_proba(X_te)[:, 1], dtype=float)
        cand_probs = {"raw": (p_ca_raw, p_te_raw)}
        if len(calib) >= MIN_PLATT and len(np.unique(y_ca)) >= 2:
            pack_p = fit_platt(p_ca_raw, y_ca)
            cand_probs["platt"] = (apply_platt(pack_p, p_ca_raw), apply_platt(pack_p, p_te_raw))
        else:
            cal_report["skipped"].append("platt_insufficient")
        if len(calib) >= MIN_ISOTONIC and len(np.unique(y_ca)) >= 2:
            pack_i = fit_isotonic(p_ca_raw, y_ca)
            cand_probs["isotonic"] = (apply_isotonic(pack_i, p_ca_raw), apply_isotonic(pack_i, p_te_raw))
        else:
            cal_report["skipped"].append("isotonic_n_calib<%s" % MIN_ISOTONIC)

        best_brier = 1e9
        for method, (p_ca, p_te_m) in cand_probs.items():
            brier_ca = float(brier_score_loss(y_ca, np.clip(p_ca, 0, 1)))
            ece_ca, mce_ca = ece_mce(y_ca, p_ca)
            rec = {"method": method, "calib_brier": round(brier_ca, 6), "calib_ece": ece_ca, "calib_mce": mce_ca, "n_calib": int(len(y_ca))}
            cal_report[method] = rec
            if method == "raw":
                continue
            if brier_ca < best_brier:
                best_brier = brier_ca
                chosen_method = method
                p_te = p_te_m
                p_ca_chosen = p_ca
        if chosen_method is None:
            chosen_method = "raw"
            p_te = p_te_raw
            p_ca_chosen = p_ca_raw
        cal_report["chosen"] = chosen_method
        cal_report["selection_rule"] = "lowest_calib_brier among Platt/Isotonic; raw only if both skipped"
        chosen_th, thresh_table = pick_threshold_on_calib(y_ca, p_ca_chosen, r_ca, d_ca)
        emit("calibrator=%s thresh=%.2f (calib only)" % (chosen_method, chosen_th))
        metav2_metrics = eval_arm(r_te, y=y_te, p=p_te, direction=d_te, th=chosen_th, psi=psi)
        fit_ok = True

    emit("score current production Meta on test ...")
    p_cur, th_cur, cur_info = score_current_meta(test, df)
    taken_cur_mask = p_cur >= th_cur
    raw_rs = apply_cd_rows(p22a, test)
    cur_frame = test.loc[taken_cur_mask].copy() if taken_cur_mask.any() else test.iloc[0:0].copy()
    cur_rs = apply_cd_rows(p22a, cur_frame) if len(cur_frame) else []
    if fit_ok and np.isfinite(p_te).all():
        v2_mask = np.asarray(p_te) >= chosen_th
        v2_frame = test.loc[v2_mask].copy() if v2_mask.any() else test.iloc[0:0].copy()
        v2_rs = apply_cd_rows(p22a, v2_frame) if len(v2_frame) else []
    else:
        v2_rs = []
    raw_m = trade_metrics(raw_rs)
    cur_m = trade_metrics(cur_rs)
    v2_cd_m = trade_metrics(v2_rs)

    y_te = test["label"].astype(int).values
    d_te = test["direction"].astype(str).values
    r_te = test["realized_r"].astype(float).values
    cur_eval = eval_arm(r_te, y=y_te, p=p_cur, direction=d_te, th=float(np.median(th_cur)), psi=None)
    curve = calibration_curve(y_te, p_te) if fit_ok else []
    cm = confusion(y_te, p_te, chosen_th) if fit_ok else {"tn": 0, "fp": 0, "fn": 0, "tp": 0}

    g = gates_pass(metav2_metrics, trained_on_certified=trained_on_certified, n_test=len(test))
    passed = all(g.values())
    keep_shadow = True if not passed else False

    result_lines = [
        "PHASE_22C_RESULT",
        "",
        "TRAINED_ON_CERTIFIED=%s" % ("YES" if trained_on_certified else "NO"),
        "MODEL_UNIVERSE=%s" % CANDIDATE,
        "N_SETUPS=%s" % len(frame),
        "N_TRAIN=%s" % len(train),
        "N_CALIB=%s" % len(calib),
        "N_TEST=%s" % len(test),
        "",
        "RAW_OOS_PF=%s" % raw_m["oos_pf"],
        "RAW_OOS_EXPR=%s" % raw_m["oos_expectancy_r"],
        "RAW_OOS_TRADES=%s" % raw_m["trades"],
        "CURRENT_META_OOS_PF=%s" % cur_m["oos_pf"],
        "CURRENT_META_OOS_EXPR=%s" % cur_m["oos_expectancy_r"],
        "CURRENT_META_OOS_TRADES=%s" % cur_m["trades"],
        "METAV2_OOS_PF=%s" % metav2_metrics.get("oos_pf"),
        "METAV2_OOS_EXPR=%s" % metav2_metrics.get("oos_expectancy_r"),
        "METAV2_OOS_TRADES=%s" % metav2_metrics.get("trades"),
        "METAV2_AFTER_CD_PF=%s" % v2_cd_m["oos_pf"],
        "METAV2_AFTER_CD_EXPR=%s" % v2_cd_m["oos_expectancy_r"],
        "",
        "PRECISION_BUY=%s" % metav2_metrics.get("precision_buy"),
        "PRECISION_SELL=%s" % metav2_metrics.get("precision_sell"),
        "BRIER=%s" % metav2_metrics.get("brier"),
        "ECE=%s" % metav2_metrics.get("ece"),
        "MCE=%s" % metav2_metrics.get("mce"),
        "PSI=%s" % metav2_metrics.get("psi"),
        "",
        "CALIBRATOR=%s" % (chosen_method or "NONE"),
        "THRESHOLD_SOURCE=CALIBRATION",
        "THRESHOLD=%s" % chosen_th,
        "",
        "GATES_PASS=%s" % ("YES" if passed else "NO"),
        "KEEP_SHADOW_MODE=%s" % ("YES" if keep_shadow else "NO"),
        "LIVE_PATCH_APPLIED=NO",
        "",
    ]
    result = "\n".join(result_lines)

    matrix = {
        "phase": "22C",
        "live_files_modified": False,
        "trained_on_certified": trained_on_certified,
        "certified_models_22b": certified or ["NONE"],
        "model_universe": [CANDIDATE],
        "mixed_models": False,
        "funnel_b": funnel,
        "n_setups": int(len(frame)),
        "split": {"train": int(len(train)), "calib": int(len(calib)), "test": int(len(test)), "embargo_bars": EMBARGO, "horizon_bars": HORIZON},
        "features": FEATURE_COLS,
        "leakage_controls": {
            "no_current_mfe_mae_as_features": True,
            "hist_mfe_mae_only_from_prior_closed_trades": True,
            "confirmed_closed_bars": True,
            "threshold_chosen_on": "calibration",
            "calibrator_chosen_on": "calibration_brier",
        },
        "purged_cv": cv,
        "comparison_test": {
            "raw": raw_m,
            "current_meta": {**cur_m, "score_info": cur_info, "filter_metrics": cur_eval},
            "meta_v2_filter": metav2_metrics,
            "meta_v2_after_cooldown": v2_cd_m,
        },
        "gates": g,
        "passed": passed,
        "confusion_matrix": cm,
        "calibration_curve": curve,
        "result_block": result,
    }
    cal_out = {
        "methods": {k: v for k, v in cal_report.items() if k in ("raw", "platt", "isotonic")},
        "chosen": chosen_method,
        "skipped": cal_report.get("skipped"),
        "selection_rule": cal_report.get("selection_rule"),
        "min_platt": MIN_PLATT,
        "min_isotonic": MIN_ISOTONIC,
        "threshold_grid": list(THRESH_GRID),
        "threshold_chosen": chosen_th,
        "threshold_table_calib": thresh_table,
        "threshold_source": "calibration_not_oos",
        "calibration_curve_test": curve,
    }
    extra = result.rstrip() + "\n\nNOTES\n" + "GATES=%s\nCV=%s\nCURRENT_META=%s\nLIVE_PATCH_APPLIED=NO\n" % (
        json.dumps(g), json.dumps(cv), json.dumps(cur_info),
    )
    (OUT / "meta_v2_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")
    (OUT / "calibration.json").write_text(json.dumps(cal_out, indent=2, default=str), encoding="utf-8")
    (OUT / "phase22c_result.txt").write_text(extra, encoding="utf-8")
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())