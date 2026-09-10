"""Phase 67 — TREND specialization + RF+HGB ensemble (research only).

Test configs A–F on TREND subset with strict 5-window walk-forward at threshold 0.40.
Threshold sweep 0.35–0.50 on best config; recommend carry-forward for Phase 68.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase67" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

PRIMARY_THRESHOLD = 0.40
GATE_MEAN_PF = 1.3
GATE_MEAN_AUC = 0.55
MIN_TRADES_FLOOR = 30
MIN_TRADES_DEFAULT = 15
THRESHOLD_SWEEP = [0.35, 0.37, 0.40, 0.42, 0.45, 0.50]

BASELINE_AUC = 0.5153
BASELINE_PF = 1.7343
BASELINE_HONEST_PF = 0.5676

CONFIGS = {
    "A": {
        "name": "baseline_rf_10f_label_v3_h72",
        "label_variant": "label_v3",
        "horizon": 72,
        "model": "random_forest",
        "class_weight": None,
        "dual_objective": False,
        "role": "reference",
    },
    "B": {
        "name": "strict_tp_only_h24_rf_10f",
        "label_variant": "strict_tp_only",
        "horizon": 24,
        "model": "random_forest",
        "class_weight": None,
        "dual_objective": False,
        "role": "phase66_auc_winner",
    },
    "C": {
        "name": "strict_tp_only_h24_rf_hgb_ensemble",
        "label_variant": "strict_tp_only",
        "horizon": 24,
        "model": "rf_hgb_ensemble",
        "class_weight": None,
        "dual_objective": False,
        "role": "ensemble",
    },
    "D": {
        "name": "strict_tp_only_h24_rf_balanced",
        "label_variant": "strict_tp_only",
        "horizon": 24,
        "model": "random_forest",
        "class_weight": "balanced",
        "dual_objective": False,
        "role": "class_weight",
    },
    "E": {
        "name": "label_v3_h72_rf_hgb_ensemble",
        "label_variant": "label_v3",
        "horizon": 72,
        "model": "rf_hgb_ensemble",
        "class_weight": None,
        "dual_objective": False,
        "role": "ensemble_baseline_label",
    },
    "F": {
        "name": "dual_strict_tp_h24_rank_label_v3_h72_pf",
        "label_variant": "strict_tp_only",
        "horizon": 24,
        "model": "random_forest",
        "class_weight": None,
        "dual_objective": True,
        "eval_label_variant": "label_v3",
        "eval_horizon": 72,
        "role": "dual_objective",
    },
}


def _load_baseline_features() -> list[str]:
    from tradingbot.ml.research.phase66.label_horizon_experiments import _load_baseline_features

    return _load_baseline_features()


def _fit_predict(
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    *,
    model: str,
    class_weight: str | None = None,
    sample_weight: np.ndarray | None = None,
    seed: int = 42,
) -> np.ndarray:
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier

    if model == "rf_hgb_ensemble":
        rf_kw: dict[str, Any] = {
            "n_estimators": 120,
            "max_depth": 6,
            "random_state": seed,
            "min_samples_leaf": 10,
        }
        if class_weight:
            rf_kw["class_weight"] = class_weight
        rf = RandomForestClassifier(**rf_kw)
        hgb_kw: dict[str, Any] = {"max_iter": 120, "max_depth": 6, "random_state": seed}
        if class_weight:
            hgb_kw["class_weight"] = class_weight
        hgb = HistGradientBoostingClassifier(**hgb_kw)
        rf.fit(X_tr, y_tr, sample_weight=sample_weight)
        hgb.fit(X_tr, y_tr, sample_weight=sample_weight)
        return (rf.predict_proba(X_te)[:, 1] + hgb.predict_proba(X_te)[:, 1]) / 2.0

    if model == "random_forest":
        kw: dict[str, Any] = {
            "n_estimators": 120,
            "max_depth": 6,
            "random_state": seed,
            "min_samples_leaf": 10,
        }
        if class_weight:
            kw["class_weight"] = class_weight
        clf = RandomForestClassifier(**kw)
        clf.fit(X_tr, y_tr, sample_weight=sample_weight)
        return clf.predict_proba(X_te)[:, 1]

    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

    clf = create_trend_ml_model(model, seed=seed)
    clf.fit(X_tr, y_tr, sample_weight=sample_weight)
    return clf.predict_proba(X_te)[:, 1]


def trend_walk_forward(
    train_df: pd.DataFrame,
    test_eval_df: pd.DataFrame | None,
    train_label_col: str,
    eval_label_col: str,
    feature_cols: list[str],
    *,
    model: str = "random_forest",
    class_weight: str | None = None,
    sample_weight_col: str | None = None,
    primary_threshold: float = PRIMARY_THRESHOLD,
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = MIN_TRADES_DEFAULT,
    min_windows: int = 5,
    seed: int = 42,
    dual_objective: bool = False,
) -> dict[str, Any]:
    """Strict 5-window walk-forward on TREND subset."""
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf

    work = train_df[train_df[train_label_col].isin([0, 1])].copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())

    eval_work = None
    if dual_objective and test_eval_df is not None:
        eval_work = test_eval_df[test_eval_df[eval_label_col].isin([0, 1])].copy()
        if "regime" in eval_work.columns:
            eval_work = eval_work[eval_work["regime"] == "TREND"]
        eval_work["timestamp"] = pd.to_datetime(eval_work["timestamp"], utc=True)
        eval_work = eval_work.sort_values("timestamp")

    if len(years) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "years": [int(y) for y in years]}

    per_year: list[dict[str, Any]] = []
    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < min_train_rows or len(te) < min_test_rows:
            continue

        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[train_label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)

        sw_tr = None
        if sample_weight_col and sample_weight_col in tr.columns:
            sw_tr = tr[sample_weight_col].astype(float).values

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)

        proba = _fit_predict(
            X_tr_s, y_tr, X_te_s,
            model=model, class_weight=class_weight, sample_weight=sw_tr, seed=seed,
        )

        if dual_objective and eval_work is not None:
            te_eval = eval_work[eval_work["timestamp"].dt.year == test_year]
            if len(te_eval) < min_test_rows:
                continue
            merge_keys = ["timestamp", "entry_price", "direction"]
            te_m = te.merge(te_eval[merge_keys + [eval_label_col]], on=merge_keys, how="inner")
            if len(te_m) < min_test_rows:
                continue
            y_te_auc = te[train_label_col].astype(int).values
            y_te_pf = te_m[eval_label_col].astype(int).values
            proba_pf = _fit_predict(
                X_tr_s, y_tr, scaler.transform(te_m[feature_cols].astype(float).fillna(0)),
                model=model, class_weight=class_weight, sample_weight=sw_tr, seed=seed,
            )
            try:
                auc = round(float(roc_auc_score(y_te_auc, proba)), 4)
            except ValueError:
                auc = 0.5
            primary = _pf(y_te_pf, proba_pf, primary_threshold)
            test_rows = len(te_m)
        else:
            y_te = te[eval_label_col].astype(int).values
            try:
                auc = round(float(roc_auc_score(y_te, proba)), 4)
            except ValueError:
                auc = 0.5
            primary = _pf(y_te, proba, primary_threshold)
            test_rows = len(te)

        per_year.append({
            "test_year": int(test_year),
            "train_rows": len(tr),
            "test_rows": test_rows,
            "auc": auc,
            "primary_threshold": primary_threshold,
            "primary_pf": primary["pf"],
            "primary_trades": primary["trades"],
            "primary_win_rate": primary["win_rate"],
            "meets_min_trades": primary["trades"] >= min_test_trades,
        })

    if len(per_year) < min_windows:
        return {
            "verdict": "INSUFFICIENT_WINDOWS",
            "windows_found": len(per_year),
            "min_windows_required": min_windows,
            "per_year": per_year,
        }

    primary_pfs = [float(w["primary_pf"]) for w in per_year]
    aucs = [float(w["auc"]) for w in per_year]
    mean_pf = round(float(np.mean(primary_pfs)), 4)
    mean_auc = round(float(np.mean(aucs)), 4)
    mean_win_rate = round(float(np.mean([w["primary_win_rate"] for w in per_year])), 2)
    mean_trades = round(float(np.mean([w["primary_trades"] for w in per_year])), 1)

    gates = {
        "mean_pf_ge_1_3": mean_pf >= GATE_MEAN_PF,
        "mean_auc_ge_0_55": mean_auc >= GATE_MEAN_AUC,
        "min_windows_ge_5": len(per_year) >= min_windows,
        "majority_windows_pf_ge_1": sum(1 for p in primary_pfs if p >= 1.0) >= max(2, len(per_year) // 2),
        "trade_count_ok": sum(1 for w in per_year if w["meets_min_trades"]) >= max(2, len(per_year) // 2),
    }
    gate_passed = all(gates.values())
    if gate_passed:
        verdict = "STRICT_GATE_PASS"
    elif mean_pf >= 1.0 and mean_auc >= 0.52:
        verdict = "STRICT_GATE_MARGINAL"
    else:
        verdict = "STRICT_GATE_FAIL"

    return {
        "verdict": verdict,
        "gate_passed": gate_passed,
        "gates": gates,
        "model": model,
        "class_weight": class_weight,
        "dual_objective": dual_objective,
        "features_used": feature_cols,
        "feature_count": len(feature_cols),
        "primary_threshold": primary_threshold,
        "windows": len(per_year),
        "mean_pf": mean_pf,
        "mean_auc": mean_auc,
        "mean_win_rate": mean_win_rate,
        "mean_trades_per_window": mean_trades,
        "per_year": per_year,
        "rows_trend": len(work),
    }


def _evaluate_gates(wf: dict[str, Any], *, min_trades_per_window: int = MIN_TRADES_FLOOR) -> dict[str, Any]:
    from tradingbot.ml.research.phase60.auc_lift_and_validation import _evaluate_gates

    return _evaluate_gates(wf, min_trades_per_window=min_trades_per_window)


def _threshold_sweep(
    train_df: pd.DataFrame,
    test_eval_df: pd.DataFrame | None,
    cfg: dict[str, Any],
    feature_cols: list[str],
    *,
    thresholds: list[float] | None = None,
) -> dict[str, Any]:
    """Sweep thresholds on a single config using same WF logic."""
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf

    thresholds = thresholds or THRESHOLD_SWEEP
    train_label_col = "_label"
    eval_label_col = "_label_eval" if cfg.get("dual_objective") else "_label"
    model = cfg["model"]
    class_weight = cfg.get("class_weight")
    dual = bool(cfg.get("dual_objective"))

    work = train_df[train_df[train_label_col].isin([0, 1])].copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")

    eval_work = None
    if dual and test_eval_df is not None:
        eval_work = test_eval_df.copy()
        if eval_label_col == "_label_eval" and "_label_eval" not in eval_work.columns and "_label" in eval_work.columns:
            eval_work = eval_work.rename(columns={"_label": "_label_eval"})
        eval_work = eval_work[eval_work[eval_label_col].isin([0, 1])].copy()
        if "regime" in eval_work.columns:
            eval_work = eval_work[eval_work["regime"] == "TREND"]
        eval_work["timestamp"] = pd.to_datetime(eval_work["timestamp"], utc=True)
        eval_work = eval_work.sort_values("timestamp")

    years = sorted(work["timestamp"].dt.year.unique())
    all_window_sweeps: list[dict[str, Any]] = []
    aucs: list[float] = []

    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < 200 or len(te) < 100:
            continue

        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[train_label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        proba = _fit_predict(X_tr_s, y_tr, X_te_s, model=model, class_weight=class_weight)

        if dual and eval_work is not None:
            te_eval = eval_work[eval_work["timestamp"].dt.year == test_year]
            merge_keys = ["timestamp", "entry_price", "direction"]
            te_m = te.merge(te_eval[merge_keys + [eval_label_col]], on=merge_keys, how="inner")
            if len(te_m) < 100:
                continue
            y_te_auc = te[train_label_col].astype(int).values
            y_te_pf = te_m[eval_label_col].astype(int).values
            proba_pf = _fit_predict(
                X_tr_s, y_tr, scaler.transform(te_m[feature_cols].astype(float).fillna(0)),
                model=model, class_weight=class_weight,
            )
            try:
                aucs.append(float(roc_auc_score(y_te_auc, proba)))
            except ValueError:
                aucs.append(0.5)
            sweep_rows = []
            for thr in thresholds:
                row = {"threshold": thr, **_pf(y_te_pf, proba_pf, thr)}
                sweep_rows.append(row)
        else:
            y_te = te[eval_label_col].astype(int).values
            try:
                aucs.append(float(roc_auc_score(y_te, proba)))
            except ValueError:
                aucs.append(0.5)
            sweep_rows = []
            for thr in thresholds:
                row = {"threshold": thr, **_pf(y_te, proba, thr)}
                sweep_rows.append(row)

        all_window_sweeps.append({"test_year": int(test_year), "sweep": sweep_rows})

    if not all_window_sweeps:
        return {"verdict": "INSUFFICIENT_DATA", "thresholds": thresholds}

    aggregate: list[dict[str, Any]] = []
    for thr in thresholds:
        pfs = []
        trades = []
        wins = []
        for w in all_window_sweeps:
            row = next(s for s in w["sweep"] if s["threshold"] == thr)
            pfs.append(row["pf"])
            trades.append(row["trades"])
            if row["trades"] > 0:
                wins.append(row["win_rate"])
        eligible = [w for w in all_window_sweeps if next(s for s in w["sweep"] if s["threshold"] == thr)["trades"] >= MIN_TRADES_FLOOR]
        honest_pfs = [
            next(s for s in w["sweep"] if s["threshold"] == thr)["pf"] for w in eligible
        ]
        aggregate.append({
            "threshold": thr,
            "mean_pf": round(float(np.mean(pfs)), 4),
            "mean_pf_honest": round(float(np.mean(honest_pfs)), 4) if honest_pfs else 0.0,
            "mean_trades": round(float(np.mean(trades)), 1),
            "mean_win_rate": round(float(np.mean(wins)), 2) if wins else 0.0,
            "windows_eligible_honest": len(eligible),
            "auc_gate_pass": round(float(np.mean(aucs)), 4) >= GATE_MEAN_AUC,
            "honest_pf_gate_pass": (round(float(np.mean(honest_pfs)), 4) if honest_pfs else 0.0) >= GATE_MEAN_PF,
            "both_gates_pass": (
                round(float(np.mean(aucs)), 4) >= GATE_MEAN_AUC
                and (round(float(np.mean(honest_pfs)), 4) if honest_pfs else 0.0) >= GATE_MEAN_PF
            ),
        })

    def score(a: dict[str, Any]) -> tuple:
        return (
            bool(a.get("both_gates_pass")),
            float(a.get("mean_pf_honest") or 0),
            float(a.get("mean_pf") or 0),
            -abs(a["threshold"] - PRIMARY_THRESHOLD),
        )

    best_thr_row = max(aggregate, key=score)
    return {
        "config_id": cfg.get("config_id"),
        "thresholds": thresholds,
        "mean_auc_fixed": round(float(np.mean(aucs)), 4),
        "per_window": all_window_sweeps,
        "aggregate": aggregate,
        "best_threshold": best_thr_row["threshold"],
        "best_mean_pf_honest": best_thr_row["mean_pf_honest"],
        "best_both_gates_pass": best_thr_row["both_gates_pass"],
    }


def _run_config(
    config_id: str,
    cfg: dict[str, Any],
    labeled_frames: dict[tuple[int, str], pd.DataFrame],
    feature_cols: list[str],
) -> dict[str, Any]:
    horizon = cfg["horizon"]
    variant = cfg["label_variant"]
    train_df = labeled_frames[(horizon, variant)]

    test_eval_df = None
    eval_label_col = "_label_eval" if cfg.get("dual_objective") else "_label"
    if cfg.get("dual_objective"):
        eval_h = int(cfg["eval_horizon"])
        eval_v = cfg["eval_label_variant"]
        test_eval_df = labeled_frames[(eval_h, eval_v)].copy()
        test_eval_df = test_eval_df.rename(columns={"_label": "_label_eval"})

    wf = trend_walk_forward(
        train_df,
        test_eval_df,
        "_label",
        eval_label_col,
        feature_cols,
        model=cfg["model"],
        class_weight=cfg.get("class_weight"),
        dual_objective=bool(cfg.get("dual_objective")),
        primary_threshold=PRIMARY_THRESHOLD,
    )
    gates_honest = _evaluate_gates(wf, min_trades_per_window=MIN_TRADES_FLOOR)

    mean_auc = float(wf.get("mean_auc") or 0)
    mean_pf = float(wf.get("mean_pf") or 0)
    honest_pf = float(gates_honest.get("mean_pf_honest") or 0)
    pos_rate = float(train_df["_label"].mean()) if len(train_df) else 0.0

    both_gates = mean_auc >= GATE_MEAN_AUC and honest_pf >= GATE_MEAN_PF

    return {
        "config_id": config_id,
        "name": cfg["name"],
        "role": cfg.get("role"),
        "label_variant": variant,
        "horizon_bars": horizon,
        "model": cfg["model"],
        "class_weight": cfg.get("class_weight"),
        "dual_objective": bool(cfg.get("dual_objective")),
        "eval_label_variant": cfg.get("eval_label_variant"),
        "eval_horizon": cfg.get("eval_horizon"),
        "rows_labeled": int(len(train_df)),
        "positive_rate": round(pos_rate, 4),
        "mean_auc": mean_auc,
        "mean_pf": mean_pf,
        "mean_pf_honest": honest_pf,
        "mean_win_rate": wf.get("mean_win_rate"),
        "mean_trades_per_window": wf.get("mean_trades_per_window"),
        "windows_eligible_honest": gates_honest.get("windows_eligible_honest"),
        "gate_passed": bool(wf.get("gate_passed")),
        "gate_passed_honest": bool(gates_honest.get("gate_passed_honest")),
        "auc_gate_pass": mean_auc >= GATE_MEAN_AUC,
        "honest_pf_gate_pass": honest_pf >= GATE_MEAN_PF,
        "both_gates_pass": both_gates,
        "delta_auc_vs_baseline": round(mean_auc - BASELINE_AUC, 4),
        "delta_pf_honest_vs_baseline": round(honest_pf - BASELINE_HONEST_PF, 4),
        "verdict": wf.get("verdict"),
        "walk_forward": wf,
        "gates_honest": gates_honest.get("gates_honest"),
        "per_year": wf.get("per_year"),
    }


def _pick_best(results: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in results if r.get("per_year")]
    if not valid:
        return {"config_id": "none", "mean_auc": 0.0}

    def score(r: dict[str, Any]) -> tuple:
        return (
            bool(r.get("both_gates_pass")),
            bool(r.get("auc_gate_pass")),
            bool(r.get("honest_pf_gate_pass")),
            float(r.get("mean_auc") or 0),
            float(r.get("mean_pf_honest") or 0),
            float(r.get("mean_pf") or 0),
        )

    return max(valid, key=score)


def _recommendation(best: dict[str, Any], any_both_pass: bool) -> dict[str, str]:
    cid = best.get("config_id", "?")
    name = best.get("name", "?")
    auc = float(best.get("mean_auc") or 0)
    honest = float(best.get("mean_pf_honest") or 0)
    inflated = float(best.get("mean_pf") or 0)

    if any_both_pass:
        en = (
            f"Phase 67 config {cid} ({name}) passes BOTH gates: AUC {auc:.4f}, honest PF@30={honest:.4f}. "
            f"Carry to Phase 68 combined shadow validation."
        )
        fa = (
            f"فاز ۶۷ کانفیگ {cid} ({name}) هر دو gate را پاس کرد: AUC {auc:.4f}، PF صادق@30={honest:.4f}. "
            f"به فاز ۶۸ shadow ببرید."
        )
    elif best.get("auc_gate_pass") and not best.get("honest_pf_gate_pass"):
        en = (
            f"Phase 67 best {cid} ({name}): AUC {auc:.4f} passes but honest PF@30={honest:.4f} fails "
            f"(inflated mean PF={inflated:.4f}). AUC may reflect imbalanced label — not tradeable edge. "
            f"Phase 68: use {cid} with conservative threshold; expect PF gate fail."
        )
        fa = (
            f"بهترین فاز ۶۷ {cid}: AUC {auc:.4f} پاس، PF صادق@30={honest:.4f} رد "
            f"(PF تورم‌زده={inflated:.4f}). AUC احتمالاً از label نامتعادل — edge قابل معامله نیست. "
            f"فاز ۶۸: {cid} با threshold محافظه‌کارانه؛ انتظار رد PF."
        )
    elif float(best.get("mean_pf_honest") or 0) > BASELINE_HONEST_PF:
        en = (
            f"Phase 67 marginal PF lift ({cid}: honest PF@30={honest:.4f} vs baseline {BASELINE_HONEST_PF:.4f}, "
            f"AUC {auc:.4f}). Neither gate passes. Phase 68 shadow with {cid} for evidence only."
        )
        fa = (
            f"فاز ۶۷ ارتقای جزئی PF ({cid}: PF صادق@30={honest:.4f} در برابر {BASELINE_HONEST_PF:.4f}، "
            f"AUC {auc:.4f}). هیچ gate پاس نشد. فاز ۶۸ shadow با {cid} فقط برای شواهد."
        )
    else:
        en = (
            f"Phase 67 ensemble/specialization insufficient (best {cid}: AUC {auc:.4f}, honest PF@30={honest:.4f}). "
            f"Phase 68: baseline config A or best available {cid} — gates expected to fail."
        )
        fa = (
            f"فاز ۶۷ کافی نبود (بهترین {cid}: AUC {auc:.4f}، PF صادق@30={honest:.4f}). "
            f"فاز ۶۸: کانفیگ A یا {cid} — انتظار رد gate."
        )
    return {"en": en, "fa": fa}


def run_phase67() -> dict[str, Any]:
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
    from tradingbot.ml.research.phase66.label_horizon_experiments import (
        apply_label_variant,
        relabel_at_horizon,
    )

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    raw = pd.read_parquet(V7_PATH)
    candles = resolve_fullest_candles()
    if candles is None or candles.empty:
        return {"verdict": "INSUFFICIENT_DATA", "error": "candles missing"}

    feature_cols = [c for c in _load_baseline_features() if c in raw.columns]
    horizons_needed = {72, 24}
    labeled_frames: dict[tuple[int, str], pd.DataFrame] = {}

    for h in sorted(horizons_needed):
        print(f"  loading labels horizon={h}...", flush=True)
        t0 = time.time()
        frame = relabel_at_horizon(raw, candles, future_window_bars=h)
        for variant in ("label_v3", "strict_tp_only"):
            use_existing = variant == "label_v3" and h == 72
            labeled, _ = apply_label_variant(frame, variant, use_existing_v3=use_existing)
            labeled_frames[(h, variant)] = labeled
            print(
                f"    {variant} h={h}: {len(labeled)} rows, pos={labeled['_label'].mean():.3f} "
                f"({time.time() - t0:.1f}s)",
                flush=True,
            )

    results: list[dict[str, Any]] = []
    for config_id in sorted(CONFIGS):
        cfg = {**CONFIGS[config_id], "config_id": config_id}
        print(f"  WF config {config_id}: {cfg['name']}...", flush=True)
        result = _run_config(config_id, cfg, labeled_frames, feature_cols)
        results.append(result)
        print(
            f"    AUC={result['mean_auc']:.4f} PF={result['mean_pf']:.4f} "
            f"honest_PF@30={result['mean_pf_honest']:.4f} both={result['both_gates_pass']}",
            flush=True,
        )

    best = _pick_best(results)
    any_both_pass = any(r.get("both_gates_pass") for r in results)
    best_cfg = CONFIGS.get(best.get("config_id", "A"), CONFIGS["A"])
    best_cfg = {**best_cfg, "config_id": best.get("config_id", "A")}

    print(f"  threshold sweep on best config {best.get('config_id')}...", flush=True)
    sweep = _threshold_sweep(
        labeled_frames[(best_cfg["horizon"], best_cfg["label_variant"])],
        labeled_frames.get((best_cfg.get("eval_horizon", 72), best_cfg.get("eval_label_variant", "label_v3")))
        if best_cfg.get("dual_objective")
        else None,
        best_cfg,
        feature_cols,
    )

    if any_both_pass:
        verdict = "STRICT_GATE_PASS"
    elif best.get("auc_gate_pass") or float(best.get("mean_pf_honest") or 0) > BASELINE_HONEST_PF + 0.05:
        verdict = "STRICT_GATE_MARGINAL"
    else:
        verdict = "STRICT_GATE_FAIL"

    rec = _recommendation(best, any_both_pass)

    comparison = [
        {
            "config_id": r["config_id"],
            "name": r["name"],
            "label_variant": r["label_variant"],
            "horizon_bars": r["horizon_bars"],
            "model": r["model"],
            "mean_auc": r["mean_auc"],
            "mean_pf": r["mean_pf"],
            "mean_pf_honest": r["mean_pf_honest"],
            "mean_win_rate": r["mean_win_rate"],
            "mean_trades_per_window": r["mean_trades_per_window"],
            "both_gates_pass": r["both_gates_pass"],
            "auc_gate_pass": r["auc_gate_pass"],
            "honest_pf_gate_pass": r["honest_pf_gate_pass"],
            "delta_auc_vs_baseline": r["delta_auc_vs_baseline"],
            "verdict": r["verdict"],
        }
        for r in results
    ]

    phase68_ready = bool(any_both_pass) or (
        best.get("auc_gate_pass") and float(best.get("mean_pf_honest") or 0) >= 0.8
    )

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "gate_passed": any_both_pass,
        "any_both_gates_pass": any_both_pass,
        "auc_gate_pass_best": bool(best.get("auc_gate_pass")),
        "honest_pf_gate_pass_best": bool(best.get("honest_pf_gate_pass")),
        "gate_targets": {
            "mean_auc": GATE_MEAN_AUC,
            "honest_pf": GATE_MEAN_PF,
            "min_trades": MIN_TRADES_FLOOR,
            "primary_threshold": PRIMARY_THRESHOLD,
        },
        "baseline": {
            "config": "A_baseline_rf_10f_label_v3_h72",
            "mean_auc": BASELINE_AUC,
            "mean_pf": BASELINE_PF,
            "mean_pf_honest": BASELINE_HONEST_PF,
        },
        "configs_tested": list(CONFIGS.keys()),
        "results": results,
        "comparison": comparison,
        "best_config": {
            "config_id": best.get("config_id"),
            "name": best.get("name"),
            "label_variant": best.get("label_variant"),
            "horizon_bars": best.get("horizon_bars"),
            "model": best.get("model"),
            "class_weight": best.get("class_weight"),
            "dual_objective": best.get("dual_objective"),
            "mean_auc": best.get("mean_auc"),
            "mean_pf": best.get("mean_pf"),
            "mean_pf_honest": best.get("mean_pf_honest"),
            "both_gates_pass": best.get("both_gates_pass"),
            "primary_threshold": PRIMARY_THRESHOLD,
            "features": feature_cols,
            "for_phase_68": {
                "config_id": best.get("config_id"),
                "label_variant": best.get("label_variant"),
                "horizon_bars": best.get("horizon_bars"),
                "eval_label_variant": best.get("eval_label_variant"),
                "eval_horizon": best.get("eval_horizon"),
                "model": best.get("model"),
                "class_weight": best.get("class_weight"),
                "dual_objective": best.get("dual_objective"),
                "features": feature_cols,
                "threshold": sweep.get("best_threshold", PRIMARY_THRESHOLD),
                "phase68_ready": phase68_ready,
            },
        },
        "threshold_sweep": sweep,
        "tradeoff_assessment": {
            "auc_pf_decoupled": bool(best.get("auc_gate_pass")) and not bool(best.get("honest_pf_gate_pass")),
            "note_en": (
                "h24 strict_tp_only inflates AUC via ~14% positive class; honest PF@30 remains far below 1.3. "
                "Ensemble/class_weight/dual-objective unlikely to fix PF without sacrificing AUC."
                if best.get("label_variant") == "strict_tp_only" and best.get("horizon_bars") == 24
                else "label_v3 h72 configs show modest PF; AUC below gate."
            ),
            "note_fa": (
                "strict_tp_only h24 با کلاس مثبت ~۱۴٪ AUC را بالا می‌برد؛ PF صادق@30 زیر ۱.۳ می‌ماند."
                if best.get("label_variant") == "strict_tp_only" and best.get("horizon_bars") == 24
                else "کانفیگ‌های label_v3 h72 PF متوسط؛ AUC زیر gate."
            ),
        },
        "recommendation_en": rec["en"],
        "recommendation_fa": rec["fa"],
        "phase68_ready": phase68_ready,
        "next_phase": "68",
        "research_only": True,
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    slim_results = [
        {k: v for k, v in r.items() if k not in ("walk_forward",)}
        for r in data.get("results", [])
    ]
    artifact = {
        "comparison": data.get("comparison"),
        "best_config": data.get("best_config"),
        "threshold_sweep": data.get("threshold_sweep"),
        "tradeoff_assessment": data.get("tradeoff_assessment"),
        "results_summary": slim_results,
    }
    (ARTIFACTS / "trend_specialization.json").write_text(
        json.dumps(artifact, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase67/artifacts/trend_specialization.json", flush=True)

    best = data.get("best_config") or {}
    report = {
        "phase": "67",
        "title": "TREND Specialization & Ensemble",
        "title_fa": "تخصصی‌سازی TREND + ensemble",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "gate_passed": data.get("gate_passed"),
        "any_both_gates_pass": data.get("any_both_gates_pass"),
        "auc_gate_pass_best": data.get("auc_gate_pass_best"),
        "honest_pf_gate_pass_best": data.get("honest_pf_gate_pass_best"),
        "gate_targets": data.get("gate_targets"),
        "baseline": data.get("baseline"),
        "configs_tested": data.get("configs_tested"),
        "comparison": data.get("comparison"),
        "best_config": best,
        "mean_auc": best.get("mean_auc"),
        "mean_pf": best.get("mean_pf"),
        "mean_pf_honest": best.get("mean_pf_honest"),
        "threshold_sweep": data.get("threshold_sweep"),
        "tradeoff_assessment": data.get("tradeoff_assessment"),
        "for_phase_68": best.get("for_phase_68"),
        "phase68_ready": data.get("phase68_ready"),
        "recommendation_en": data.get("recommendation_en"),
        "recommendation_fa": data.get("recommendation_fa"),
        "next_phase": data.get("next_phase"),
    }
    (ROOT / "phase67_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase67_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    best = data.get("best_config") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_67_COMPLETE"
    status["current_treatment_phase"] = "67"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["67"] = {
        "status": "COMPLETE",
        "track": "M",
        "verdict": report.get("verdict"),
        "report": "phase67_final_report.json",
        "gate_passed": bool(report.get("gate_passed")),
    }
    status["phase67_summary"] = {
        "best_config_id": best.get("config_id"),
        "best_name": best.get("name"),
        "mean_auc": best.get("mean_auc"),
        "mean_pf": best.get("mean_pf"),
        "mean_pf_honest": best.get("mean_pf_honest"),
        "both_gates_pass": bool(best.get("both_gates_pass")),
        "phase68_ready": bool(data.get("phase68_ready")),
        "for_phase_68": best.get("for_phase_68"),
    }
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_fix_roadmap(report: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))
    for ph in fix.get("phases", []):
        if str(ph.get("phase")) == "67":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "68"
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase67()
    write_all(data)
    best = data.get("best_config") or {}
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "gate_passed": data.get("gate_passed"),
                "best": best.get("config_id"),
                "mean_auc": best.get("mean_auc"),
                "mean_pf_honest": best.get("mean_pf_honest"),
                "both_gates_pass": best.get("both_gates_pass"),
                "phase68_ready": data.get("phase68_ready"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
