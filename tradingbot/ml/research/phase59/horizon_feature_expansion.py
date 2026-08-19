"""Phase 59 — label horizon sweep, feature expansion, ensemble (research only)."""

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

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase59" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

HORIZONS = [36, 48, 72, 96, 120]
PRIMARY_THRESHOLD = 0.40
GATE_MEAN_PF = 1.3
GATE_MEAN_AUC = 0.55

TOP_5_FEATURES = [
    "tick_volume_proxy",
    "atr_14",
    "realized_vol_20",
    "rsi_14",
    "macd_histogram",
]
EXTRA_5_FEATURES = [
    "ema200_distance",
    "momentum_5",
    "range_pct",
    "bar_spread_pct",
    "ml_confidence",
]

HORIZON_SAMPLE_SIZE = 5000
HORIZON_SAMPLE_SEED = 42


def _load_feature_sets() -> tuple[list[str], list[str]]:
    r55 = ROOT / "phase55_final_report.json"
    if r55.is_file():
        feats = list(json.loads(r55.read_text(encoding="utf-8")).get("top_features") or [])
        if len(feats) >= 10:
            return feats[:5], feats[:10]
        if len(feats) >= 5:
            extra = [f for f in EXTRA_5_FEATURES if f not in feats[:5]]
            return feats[:5], feats[:5] + extra[:5]
    return list(TOP_5_FEATURES), list(TOP_5_FEATURES) + list(EXTRA_5_FEATURES)


def _pf_from_labels(labels: list[int]) -> float:
    wins = sum(1 for x in labels if x == 1)
    losses = sum(1 for x in labels if x == 0)
    if losses == 0:
        return 2.0 if wins > 0 else 0.0
    return round(wins / losses, 4)


def _load_trend_df(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    return work


def _resolve_row_label(
    candles: pd.DataFrame,
    row: pd.Series,
    *,
    future_window_bars: int,
) -> int | None:
    from tradingbot.ml.dataset.schema import Label
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
    from tradingbot.ml.research.phase49.bar_index import resolve_bar_index

    idx = int(row["bar_index"]) if pd.notna(row.get("bar_index")) else resolve_bar_index(candles, row["timestamp"])
    if idx < 20 or idx >= len(candles) - future_window_bars - 1:
        return None

    direction = int(row["direction"])
    entry = float(row["entry_price"])
    sl = float(row.get("stop_loss_v3", row.get("stop_loss", 0)))
    tp = float(row.get("take_profit_v3", row.get("take_profit", 0)))
    if sl <= 0 or tp <= 0:
        return None

    resolved = resolve_label_with_sl_tp(
        candles,
        idx,
        direction,
        sl,
        tp,
        future_window_bars=future_window_bars,
        entry_price=entry,
    )
    label = int(resolved["label"])
    if label == int(Label.NO_RESOLUTION):
        return None
    return 1 if label == int(Label.TP_FIRST) else 0


def relabel_dataframe(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    future_window_bars: int,
    label_col: str = "label_horizon",
) -> pd.DataFrame:
    """Re-resolve binary labels for all rows with valid SL/TP."""
    out = df.copy()
    labels: list[int | None] = []
    for _, row in out.iterrows():
        labels.append(_resolve_row_label(candles, row, future_window_bars=future_window_bars))
    out[label_col] = labels
    return out


def horizon_sweep_sample(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    horizons: list[int] | None = None,
    sample_size: int = HORIZON_SAMPLE_SIZE,
    seed: int = HORIZON_SAMPLE_SEED,
) -> dict[str, Any]:
    """Sample-based PF proxy / win-rate sweep across label horizons (speed)."""
    horizons = horizons or HORIZONS
    work = _load_trend_df(df)
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)

    eligible = work[
        work["stop_loss_v3"].astype(float).gt(0) & work["take_profit_v3"].astype(float).gt(0)
    ]
    n = min(sample_size, len(eligible))
    if n <= 0:
        return {"verdict": "INSUFFICIENT_DATA", "sample_size": 0}

    if len(eligible) > n:
        by_year = []
        for year, grp in eligible.groupby(eligible["timestamp"].dt.year):
            share = max(1, int(round(n * len(grp) / len(eligible))))
            by_year.append(grp.sample(n=min(share, len(grp)), random_state=seed + int(year)))
        sample = pd.concat(by_year).head(n)
        if len(sample) < n:
            remainder = eligible.drop(sample.index).sample(
                n=min(n - len(sample), len(eligible) - len(sample)),
                random_state=seed,
            )
            sample = pd.concat([sample, remainder])
    else:
        sample = eligible

    per_horizon: list[dict[str, Any]] = []
    for horizon in horizons:
        binary_labels: list[int] = []
        no_resolution = 0
        skipped = 0
        for _, row in sample.iterrows():
            lbl = _resolve_row_label(candles, row, future_window_bars=horizon)
            if lbl is None:
                no_resolution += 1
                skipped += 1
                continue
            binary_labels.append(lbl)

        wins = sum(1 for x in binary_labels if x == 1)
        losses = sum(1 for x in binary_labels if x == 0)
        per_horizon.append({
            "future_window_bars": horizon,
            "sample_rows": len(sample),
            "binary_rows": len(binary_labels),
            "no_resolution_rows": no_resolution,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / max(len(binary_labels), 1) * 100, 2),
            "pf_proxy": _pf_from_labels(binary_labels),
        })

    best = max(per_horizon, key=lambda x: (x["pf_proxy"], x["win_rate_pct"]))
    baseline = next((h for h in per_horizon if h["future_window_bars"] == 72), per_horizon[0])
    return {
        "approach": "stratified_year_sample",
        "sample_size_target": sample_size,
        "sample_size_actual": len(sample),
        "seed": seed,
        "horizons_tested": horizons,
        "per_horizon": per_horizon,
        "best_horizon": best["future_window_bars"],
        "best_pf_proxy": best["pf_proxy"],
        "best_win_rate_pct": best["win_rate_pct"],
        "baseline_horizon_72_pf_proxy": baseline["pf_proxy"],
        "baseline_horizon_72_win_rate_pct": baseline["win_rate_pct"],
        "pf_delta_vs_72": round(best["pf_proxy"] - baseline["pf_proxy"], 4),
    }


def ensemble_trend_walk_forward(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    primary_threshold: float = PRIMARY_THRESHOLD,
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = 15,
    min_windows: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """RF + HistGradientBoosting average proba on TREND subset."""
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf
    from tradingbot.ml.research.phase58.trend_only_model import GATE_MEAN_AUC, GATE_MEAN_PF

    work = df[df[label_col].isin([0, 1])].copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())

    if len(years) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "years": [int(y) for y in years]}

    per_year: list[dict[str, Any]] = []
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
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)

        rf = RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10,
        )
        hgb = HistGradientBoostingClassifier(max_iter=120, max_depth=6, random_state=seed)
        rf.fit(X_tr_s, y_tr)
        hgb.fit(X_tr_s, y_tr)
        proba = (rf.predict_proba(X_te_s)[:, 1] + hgb.predict_proba(X_te_s)[:, 1]) / 2.0

        try:
            auc = round(float(roc_auc_score(y_te, proba)), 4)
        except ValueError:
            auc = 0.5

        primary = _pf(y_te, proba, primary_threshold)
        per_year.append({
            "test_year": int(test_year),
            "train_rows": len(tr),
            "test_rows": len(te),
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
    windows_pf_above_1 = sum(1 for p in primary_pfs if p >= 1.0)
    windows_pf_above_1_3 = sum(1 for p in primary_pfs if p >= GATE_MEAN_PF)
    trade_ok = sum(1 for w in per_year if w["meets_min_trades"])

    gates = {
        "mean_pf_ge_1_3": mean_pf >= GATE_MEAN_PF,
        "mean_auc_ge_0_55": mean_auc >= GATE_MEAN_AUC,
        "min_windows_ge_5": len(per_year) >= min_windows,
        "majority_windows_pf_ge_1": windows_pf_above_1 >= max(2, len(per_year) // 2),
        "trade_count_ok": trade_ok >= max(2, len(per_year) // 2),
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
        "regime": "TREND",
        "model": "rf_hgb_ensemble",
        "features_used": feature_cols,
        "feature_count": len(feature_cols),
        "primary_threshold": primary_threshold,
        "windows": len(per_year),
        "mean_pf": mean_pf,
        "mean_auc": mean_auc,
        "windows_pf_above_1": windows_pf_above_1,
        "windows_pf_above_1_3": windows_pf_above_1_3,
        "per_year": per_year,
        "rows_trend": len(work),
        "gate_targets": {"mean_pf": GATE_MEAN_PF, "mean_auc": GATE_MEAN_AUC},
    }


def _pick_best_config(
    horizon: dict[str, Any],
    feature_runs: dict[str, Any],
    ensemble: dict[str, Any],
    baseline_wf: dict[str, Any],
    *,
    best_horizon: int,
    relabeled_wf: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = [
        {
            "config_id": "baseline_rf_5f_label_v3",
            "source": "phase58_baseline",
            "horizon": 72,
            "feature_count": 5,
            "model": "random_forest",
            "wf": baseline_wf,
        },
        {
            "config_id": "rf_10f_label_v3",
            "source": "feature_expansion",
            "horizon": 72,
            "feature_count": 10,
            "model": "random_forest",
            "wf": feature_runs.get("rf_10_features") or {},
        },
        {
            "config_id": "rf_5f_label_v3",
            "source": "feature_expansion",
            "horizon": 72,
            "feature_count": 5,
            "model": "random_forest",
            "wf": feature_runs.get("rf_5_features") or {},
        },
        {
            "config_id": f"ensemble_10f_label_v3",
            "source": "ensemble",
            "horizon": 72,
            "feature_count": 10,
            "model": "rf_hgb_ensemble",
            "wf": ensemble,
        },
        {
            "config_id": f"ensemble_5f_label_v3",
            "source": "ensemble",
            "horizon": 72,
            "feature_count": 5,
            "model": "rf_hgb_ensemble",
            "wf": feature_runs.get("ensemble_5_features") or {},
        },
    ]
    if relabeled_wf and relabeled_wf.get("per_year"):
        candidates.append({
            "config_id": f"rf_10f_horizon_{best_horizon}",
            "source": "horizon_relabel",
            "horizon": best_horizon,
            "feature_count": 10,
            "model": "random_forest",
            "wf": relabeled_wf,
        })

    scored: list[dict[str, Any]] = []
    for c in candidates:
        wf = c.get("wf") or {}
        if not wf.get("per_year"):
            continue
        scored.append({
            **c,
            "mean_pf": float(wf.get("mean_pf") or 0),
            "mean_auc": float(wf.get("mean_auc") or 0),
            "gate_passed": bool(wf.get("gate_passed")),
            "verdict": wf.get("verdict"),
        })

    if not scored:
        return {"config_id": "none", "mean_pf": 0.0, "mean_auc": 0.0, "gate_passed": False}

    best = max(scored, key=lambda x: (x["mean_pf"], x["mean_auc"], x["gate_passed"]))
    return best


def _estimate_proximity(wf: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.ml.research.phase51.profitability_score import profitability_proximity

    r52 = ROOT / "phase52_final_report.json"
    label_match = 100.0
    if r52.is_file():
        label_match = float(json.loads(r52.read_text(encoding="utf-8")).get("stored_vs_production_match_pct") or 100.0)

    return profitability_proximity(
        strict_gate_passed=bool(wf.get("gate_passed")),
        mean_pf=float(wf.get("mean_pf") or 0),
        mean_auc=float(wf.get("mean_auc") or 0),
        windows_count=int(wf.get("windows") or 0),
        windows_pf_above_1_3=int(wf.get("windows_pf_above_1_3") or 0),
        raw_ml_pf=float(wf.get("mean_pf") or 0),
        executed_pf=0.0,
        label_prod_match_pct=label_match,
        v7_rows=int(wf.get("rows_trend") or 0),
    )


def _recommendation(best: dict[str, Any], gate_passed: bool) -> str:
    if gate_passed:
        return (
            f"Phase 59 best config ({best.get('config_id')}) passed strict re-gate — "
            "eligible for shadow/paper validation (research only)."
        )
    mean_pf = float(best.get("mean_pf") or 0)
    mean_auc = float(best.get("mean_auc") or 0)
    if mean_pf >= 1.0:
        return (
            f"Phase 59 marginal (best {best.get('config_id')}: PF {mean_pf:.2f}, AUC {mean_auc:.4f}). "
            "Horizon/feature tuning insufficient alone — execution funnel remains primary blocker."
        )
    return (
        f"Phase 59 failed strict re-gate (best PF {mean_pf:.2f}, AUC {mean_auc:.4f}). "
        "Label horizon + feature expansion + ensemble did not recover edge. "
        "Next: new label definition or execution-path counterfactuals."
    )


def run_phase59() -> dict[str, Any]:
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
    from tradingbot.ml.research.phase58.trend_only_model import trend_only_strict_walk_forward

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    feats_5, feats_10 = _load_feature_sets()
    avail_5 = [c for c in feats_5 if c in df.columns]
    avail_10 = [c for c in feats_10 if c in df.columns]

    candles = resolve_fullest_candles()
    horizon_result: dict[str, Any] = {"verdict": "SKIPPED", "error": "candles unavailable"}
    if candles is not None and not candles.empty:
        horizon_result = horizon_sweep_sample(df, candles)

    best_horizon = int(horizon_result.get("best_horizon") or 72)

    # B) Feature expansion — RF 5 vs 10 on label_v3
    wf_5 = trend_only_strict_walk_forward(
        df, "label_v3", avail_5, primary_threshold=PRIMARY_THRESHOLD,
    )
    wf_10 = trend_only_strict_walk_forward(
        df, "label_v3", avail_10, primary_threshold=PRIMARY_THRESHOLD,
    )

    feature_expansion = {
        "rf_5_features": {
            "features": avail_5,
            "mean_pf": wf_5.get("mean_pf"),
            "mean_auc": wf_5.get("mean_auc"),
            "verdict": wf_5.get("verdict"),
            "gate_passed": wf_5.get("gate_passed"),
            "windows_pf_above_1_3": wf_5.get("windows_pf_above_1_3"),
        },
        "rf_10_features": {
            "features": avail_10,
            "mean_pf": wf_10.get("mean_pf"),
            "mean_auc": wf_10.get("mean_auc"),
            "verdict": wf_10.get("verdict"),
            "gate_passed": wf_10.get("gate_passed"),
            "windows_pf_above_1_3": wf_10.get("windows_pf_above_1_3"),
        },
        "delta_mean_pf": round(float(wf_10.get("mean_pf") or 0) - float(wf_5.get("mean_pf") or 0), 4),
        "delta_mean_auc": round(float(wf_10.get("mean_auc") or 0) - float(wf_5.get("mean_auc") or 0), 4),
        "better_feature_set": "10" if float(wf_10.get("mean_pf") or 0) >= float(wf_5.get("mean_pf") or 0) else "5",
    }

    # C) Ensemble on 10 features (and 5 for comparison)
    ensemble_10 = ensemble_trend_walk_forward(df, "label_v3", avail_10)
    ensemble_5 = ensemble_trend_walk_forward(df, "label_v3", avail_5)
    feature_expansion["ensemble_5_features"] = ensemble_5

    ensemble_comparison = {
        "ensemble_10f": {
            "mean_pf": ensemble_10.get("mean_pf"),
            "mean_auc": ensemble_10.get("mean_auc"),
            "verdict": ensemble_10.get("verdict"),
            "gate_passed": ensemble_10.get("gate_passed"),
        },
        "ensemble_5f": {
            "mean_pf": ensemble_5.get("mean_pf"),
            "mean_auc": ensemble_5.get("mean_auc"),
            "verdict": ensemble_5.get("verdict"),
            "gate_passed": ensemble_5.get("gate_passed"),
        },
        "rf_10f_baseline": {
            "mean_pf": wf_10.get("mean_pf"),
            "mean_auc": wf_10.get("mean_auc"),
        },
        "ensemble_beats_rf_10f": float(ensemble_10.get("mean_pf") or 0) > float(wf_10.get("mean_pf") or 0),
        "delta_pf_vs_rf_10f": round(float(ensemble_10.get("mean_pf") or 0) - float(wf_10.get("mean_pf") or 0), 4),
    }

    # Relabel full TREND set for best horizon if different from 72
    relabeled_wf: dict[str, Any] = {}
    if candles is not None and best_horizon != 72:
        relabeled = relabel_dataframe(_load_trend_df(df), candles, future_window_bars=best_horizon)
        relabeled = relabeled[relabeled["label_horizon"].isin([0, 1])]
        relabeled_wf = trend_only_strict_walk_forward(
            relabeled, "label_horizon", avail_10, primary_threshold=PRIMARY_THRESHOLD,
        )
        relabeled_wf["horizon_used"] = best_horizon
        relabeled_wf["relabeled_rows"] = len(relabeled)

    # D) Re-gate — pick best config
    best_config = _pick_best_config(
        horizon_result,
        {"rf_5_features": wf_5, "rf_10_features": wf_10, "ensemble_5_features": ensemble_5},
        ensemble_10,
        wf_5,
        best_horizon=best_horizon,
        relabeled_wf=relabeled_wf,
    )
    best_wf = best_config.get("wf") or {}
    proximity = _estimate_proximity(best_wf) if best_wf.get("per_year") else {}

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizon_sweep": horizon_result,
        "feature_expansion": feature_expansion,
        "ensemble_comparison": ensemble_comparison,
        "relabeled_horizon_wf": relabeled_wf,
        "best_config": best_config,
        "re_gate": best_wf,
        "proximity_update": proximity,
        "recommendation": _recommendation(best_config, bool(best_wf.get("gate_passed"))),
        "research_only": True,
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    re_gate = data.get("re_gate") or {}
    best = data.get("best_config") or {}

    payload = {
        "horizon_sweep": data.get("horizon_sweep"),
        "feature_expansion": data.get("feature_expansion"),
        "ensemble_comparison": data.get("ensemble_comparison"),
        "relabeled_horizon_wf": data.get("relabeled_horizon_wf"),
        "best_config": best,
        "re_gate": re_gate,
    }
    (ARTIFACTS / "horizon_feature_expansion.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase59/artifacts/horizon_feature_expansion.json", flush=True)

    report = {
        "phase": "59",
        "title": "Horizon Sweep + Feature Expansion + Ensemble",
        "title_fa": "جاروب افق برچسب + گسترش ویژگی + ensemble",
        "timestamp_utc": data["now"],
        "verdict": re_gate.get("verdict", "INCOMPLETE"),
        "research_only": True,
        "gate_passed": re_gate.get("gate_passed", False),
        "gates": re_gate.get("gates"),
        "gate_targets": re_gate.get("gate_targets"),
        "best_config": best,
        "horizon_sweep": data.get("horizon_sweep"),
        "feature_expansion": data.get("feature_expansion"),
        "ensemble_comparison": data.get("ensemble_comparison"),
        "relabeled_horizon_wf": {
            "horizon": (data.get("relabeled_horizon_wf") or {}).get("horizon_used"),
            "mean_pf": (data.get("relabeled_horizon_wf") or {}).get("mean_pf"),
            "mean_auc": (data.get("relabeled_horizon_wf") or {}).get("mean_auc"),
            "relabeled_rows": (data.get("relabeled_horizon_wf") or {}).get("relabeled_rows"),
        },
        "mean_pf": re_gate.get("mean_pf"),
        "mean_auc": re_gate.get("mean_auc"),
        "windows": re_gate.get("windows"),
        "windows_pf_above_1_3": re_gate.get("windows_pf_above_1_3"),
        "per_year": re_gate.get("per_year"),
        "rows_trend": re_gate.get("rows_trend"),
        "proximity_update": data.get("proximity_update"),
        "recommendation": data.get("recommendation"),
    }

    (ROOT / "phase59_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase59_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_treatment_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    proximity = report.get("proximity_update") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "TREATMENT_PHASE_59_COMPLETE"
    status["strict_gate_passed"] = bool(report.get("gate_passed"))
    status["proximity_score"] = proximity.get("proximity_score")
    status["proximity_band"] = proximity.get("proximity_band")
    status["how_close_pct"] = proximity.get("proximity_score")
    status["current_treatment_phase"] = "59"
    status["next_step"] = report.get("recommendation", "")

    if report.get("gate_passed"):
        status["engineering_verdict"] = "INTEGRATION_REVIEW_ELIGIBLE"
    else:
        status["engineering_verdict"] = "BLOCK_PRODUCTION_INTEGRATION"

    status.setdefault("treatment_phases", {})["59"] = {
        "status": "COMPLETE",
        "track": "A",
        "verdict": report.get("verdict"),
        "report": "phase59_final_report.json",
        "gate_passed": bool(report.get("gate_passed")),
    }
    status["phase59_summary"] = {
        "best_config": (report.get("best_config") or {}).get("config_id"),
        "best_horizon": (report.get("horizon_sweep") or {}).get("best_horizon"),
        "mean_pf": report.get("mean_pf"),
        "mean_auc": report.get("mean_auc"),
        "gate_passed": bool(report.get("gate_passed")),
        "ensemble_beats_rf": (data.get("ensemble_comparison") or {}).get("ensemble_beats_rf_10f"),
        "feature_set_winner": (report.get("feature_expansion") or {}).get("better_feature_set"),
    }

    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_treatment_roadmap(report: dict) -> None:
    path = ROOT / "TREATMENT_ROADMAP.json"
    if not path.is_file():
        return
    roadmap = json.loads(path.read_text(encoding="utf-8"))

    phase59 = {
        "phase": "59",
        "name_en": "Horizon Sweep + Feature Expansion + Ensemble",
        "name_fa": "جاروب افق برچسب + گسترش ویژگی + ensemble",
        "track": "A",
        "objective": (
            "Sweep label horizons on TREND v7 sample; compare RF 5 vs 10 features; "
            "RF+HGB ensemble; strict re-gate at threshold 0.40."
        ),
        "inputs": [
            "tradingbot/ml/research/phase49/artifacts/dataset_v7_ml_signals.parquet",
            "phase35/label_alignment.py resolve_label_with_sl_tp",
            "phase55 top-10 features",
            "phase58 trend_only_strict_walk_forward patterns",
        ],
        "outputs": [
            "phase59_final_report.json",
            "tradingbot/ml/research/phase59/artifacts/horizon_feature_expansion.json",
        ],
        "success_criteria": {"strict_gate_pass": True},
        "dependencies": ["phase58"],
        "status": "COMPLETE",
        "runner": "tradingbot/ml/research/phase59/horizon_feature_expansion.py",
        "verdict": report.get("verdict"),
        "gate_passed": bool(report.get("gate_passed")),
    }

    phases = roadmap.setdefault("phases", [])
    replaced = False
    for i, ph in enumerate(phases):
        if str(ph.get("phase")) == "59":
            phases[i] = phase59
            replaced = True
            break
    if not replaced:
        phases.append(phase59)

    pipeline = roadmap.setdefault("pipeline", {})
    pipeline["current_phase"] = "59"
    order = pipeline.setdefault("execution_order", [])
    if "59" not in order:
        order.append("59")

    roadmap["updated_utc"] = report["timestamp_utc"]
    path.write_text(json.dumps(roadmap, indent=2), encoding="utf-8")
    print("  updated TREATMENT_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase59()
    write_all(data)
    re_gate = data.get("re_gate") or {}
    print(json.dumps({
        "verdict": re_gate.get("verdict"),
        "gate_passed": re_gate.get("gate_passed"),
        "mean_pf": re_gate.get("mean_pf"),
        "mean_auc": re_gate.get("mean_auc"),
        "best_config": (data.get("best_config") or {}).get("config_id"),
        "best_horizon": (data.get("horizon_sweep") or {}).get("best_horizon"),
        "proximity_score": (data.get("proximity_update") or {}).get("proximity_score"),
    }, indent=2))


if __name__ == "__main__":
    main()
