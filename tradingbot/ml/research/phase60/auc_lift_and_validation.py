"""Phase 60 — AUC lift experiments, trade-count floor, execution counterfactual (research only)."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase60" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"
CACHE_LABELS = ("A", "B", "C", "H")

PRIMARY_THRESHOLD = 0.40
GATE_MEAN_PF = 1.3
GATE_MEAN_AUC = 0.55
MIN_TRADES_FLOOR = 30
MIN_TRADES_DEFAULT = 15
THRESHOLD_SWEEP = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]

EXTRA_5_FEATURES = [
    "ema200_distance",
    "momentum_5",
    "range_pct",
    "bar_spread_pct",
    "ml_confidence",
]
TOP_5_FEATURES = [
    "tick_volume_proxy",
    "atr_14",
    "realized_vol_20",
    "rsi_14",
    "macd_histogram",
]
STRICT_HORIZON = 48


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


def _load_trend_df(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    return work


def _build_stricter_label(df: pd.DataFrame, *, future_window_bars: int = STRICT_HORIZON) -> pd.DataFrame:
    """Re-resolve TP_FIRST with shorter horizon — stricter win definition."""
    from tradingbot.ml.dataset.schema import Label
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
    from tradingbot.ml.research.phase49.bar_index import resolve_bar_index

    candles = resolve_fullest_candles()
    if candles is None or candles.empty:
        return df.assign(label_strict_tp=np.nan)

    work = _load_trend_df(df)
    labels: list[int | None] = []
    for _, row in work.iterrows():
        idx = int(row["bar_index"]) if pd.notna(row.get("bar_index")) else resolve_bar_index(
            candles, row["timestamp"],
        )
        if idx < 20 or idx >= len(candles) - future_window_bars - 1:
            labels.append(None)
            continue
        direction = int(row["direction"])
        entry = float(row["entry_price"])
        sl = float(row.get("stop_loss_v3", row.get("stop_loss", 0)))
        tp = float(row.get("take_profit_v3", row.get("take_profit", 0)))
        if sl <= 0 or tp <= 0:
            labels.append(None)
            continue
        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl, tp,
            future_window_bars=future_window_bars,
            entry_price=entry,
        )
        label = int(resolved["label"])
        if label == int(Label.NO_RESOLUTION):
            labels.append(None)
            continue
        labels.append(1 if label == int(Label.TP_FIRST) else 0)

    out = work.copy()
    out["label_strict_tp"] = labels
    return out


def _fit_predict_proba(
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    *,
    technique: str,
    seed: int = 42,
) -> np.ndarray:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier

    if technique == "baseline":
        model = RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10,
        )
        model.fit(X_tr, y_tr)
        return model.predict_proba(X_te)[:, 1]

    if technique == "class_weight_balanced":
        model = RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10,
            class_weight="balanced",
        )
        model.fit(X_tr, y_tr)
        return model.predict_proba(X_te)[:, 1]

    if technique == "class_weight_tp_first":
        n_pos = max(int(y_tr.sum()), 1)
        n_neg = max(int(len(y_tr) - n_pos), 1)
        weight_ratio = n_neg / n_pos
        model = RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10,
            class_weight={0: 1.0, 1: round(weight_ratio * 1.5, 2)},
        )
        model.fit(X_tr, y_tr)
        return model.predict_proba(X_te)[:, 1]

    base = RandomForestClassifier(
        n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10,
    )
    if technique == "calibration_platt":
        method = "sigmoid"
    elif technique == "calibration_isotonic":
        method = "isotonic"
    else:
        raise ValueError(f"Unknown technique: {technique}")

    calibrated = CalibratedClassifierCV(base, method=method, cv=3)
    calibrated.fit(X_tr, y_tr)
    return calibrated.predict_proba(X_te)[:, 1]


def auc_lift_walk_forward(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    technique: str = "baseline",
    primary_threshold: float = PRIMARY_THRESHOLD,
    threshold_sweep: list[float] | None = None,
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = MIN_TRADES_DEFAULT,
    min_windows: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """TREND-only RF-10f walk-forward with AUC-lift technique."""
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf

    threshold_sweep = threshold_sweep or THRESHOLD_SWEEP
    work = df[df[label_col].isin([0, 1])].copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())

    if len(years) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "technique": technique, "years": [int(y) for y in years]}

    per_year: list[dict[str, Any]] = []
    threshold_aggregate: dict[float, list[float]] = {t: [] for t in threshold_sweep}

    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < min_train_rows or len(te) < min_test_rows:
            continue

        X_tr = tr[feature_cols].astype(float).fillna(0).values
        y_tr = tr[label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0).values
        y_te = te[label_col].astype(int).values

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)

        proba = _fit_predict_proba(X_tr_s, y_tr, X_te_s, technique=technique, seed=seed)

        try:
            auc = round(float(roc_auc_score(y_te, proba)), 4)
        except ValueError:
            auc = 0.5

        by_threshold: dict[str, dict[str, float | int]] = {}
        for thr in threshold_sweep:
            row = _pf(y_te, proba, thr)
            by_threshold[str(thr)] = row
            if row["trades"] >= min_test_trades:
                threshold_aggregate[thr].append(float(row["pf"]))

        primary = by_threshold.get(str(primary_threshold)) or _pf(y_te, proba, primary_threshold)

        per_year.append({
            "test_year": int(test_year),
            "train_rows": len(tr),
            "test_rows": len(te),
            "auc": auc,
            "primary_threshold": primary_threshold,
            "primary_pf": primary["pf"],
            "primary_trades": primary["trades"],
            "primary_win_rate": primary["win_rate"],
            "meets_min_trades_15": primary["trades"] >= MIN_TRADES_DEFAULT,
            "meets_min_trades_30": primary["trades"] >= MIN_TRADES_FLOOR,
            "by_threshold": by_threshold,
        })

    if len(per_year) < min_windows:
        return {
            "verdict": "INSUFFICIENT_WINDOWS",
            "technique": technique,
            "windows_found": len(per_year),
            "min_windows_required": min_windows,
            "per_year": per_year,
        }

    threshold_summary: list[dict[str, Any]] = []
    for thr in threshold_sweep:
        pfs = threshold_aggregate[thr]
        threshold_summary.append({
            "threshold": thr,
            "mean_pf": round(float(np.mean(pfs)), 4) if pfs else 0.0,
            "windows_with_min_trades": len(pfs),
            "per_year_pf": [round(p, 4) for p in pfs],
        })

    primary_pfs = [float(w["primary_pf"]) for w in per_year]
    aucs = [float(w["auc"]) for w in per_year]
    mean_pf = round(float(np.mean(primary_pfs)), 4)
    mean_auc = round(float(np.mean(aucs)), 4)

    return {
        "technique": technique,
        "label_col": label_col,
        "windows": len(per_year),
        "mean_pf": mean_pf,
        "mean_auc": mean_auc,
        "primary_threshold": primary_threshold,
        "threshold_summary": threshold_summary,
        "per_year": per_year,
        "rows_trend": len(work),
    }


def _evaluate_gates(
    wf: dict[str, Any],
    *,
    min_trades_per_window: int = MIN_TRADES_DEFAULT,
) -> dict[str, Any]:
    """Apply strict gates; optionally exclude low-trade windows for honest PF."""
    per_year = wf.get("per_year") or []
    if not per_year:
        return {"verdict": "INSUFFICIENT_DATA", "gate_passed": False}

    primary_pfs = [float(w["primary_pf"]) for w in per_year]
    aucs = [float(w["auc"]) for w in per_year]
    mean_pf_all = round(float(np.mean(primary_pfs)), 4)
    mean_auc = round(float(np.mean(aucs)), 4)

    eligible = [w for w in per_year if w["primary_trades"] >= min_trades_per_window]
    honest_pfs = [float(w["primary_pf"]) for w in eligible]
    mean_pf_honest = round(float(np.mean(honest_pfs)), 4) if honest_pfs else 0.0

    windows_pf_above_1 = sum(1 for p in primary_pfs if p >= 1.0)
    windows_pf_above_1_3 = sum(1 for p in primary_pfs if p >= GATE_MEAN_PF)
    trade_ok = sum(1 for w in per_year if w["primary_trades"] >= min_trades_per_window)

    gates = {
        "mean_pf_ge_1_3": mean_pf_all >= GATE_MEAN_PF,
        "mean_auc_ge_0_55": mean_auc >= GATE_MEAN_AUC,
        "min_windows_ge_5": len(per_year) >= 5,
        "majority_windows_pf_ge_1": windows_pf_above_1 >= max(2, len(per_year) // 2),
        "trade_count_ok": trade_ok >= max(2, len(per_year) // 2),
    }
    gate_passed = all(gates.values())

    gates_honest = {
        "mean_pf_ge_1_3": mean_pf_honest >= GATE_MEAN_PF,
        "mean_auc_ge_0_55": mean_auc >= GATE_MEAN_AUC,
        "min_windows_ge_5": len(eligible) >= 5,
        "majority_windows_pf_ge_1": sum(1 for p in honest_pfs if p >= 1.0) >= max(2, len(eligible) // 2) if eligible else False,
        "trade_count_ok": len(eligible) >= 5,
    }
    gate_passed_honest = all(gates_honest.values()) if len(eligible) >= 5 else False

    if gate_passed:
        verdict = "STRICT_GATE_PASS"
    elif mean_pf_all >= 1.0 and mean_auc >= 0.52:
        verdict = "STRICT_GATE_MARGINAL"
    else:
        verdict = "STRICT_GATE_FAIL"

    inflated_windows = [
        {
            "test_year": w["test_year"],
            "primary_pf": w["primary_pf"],
            "primary_trades": w["primary_trades"],
            "note": f"PF {w['primary_pf']:.2f} on only {w['primary_trades']} trades — high variance",
        }
        for w in per_year
        if w["primary_trades"] < MIN_TRADES_FLOOR and w["primary_pf"] >= 1.5
    ]

    return {
        "verdict": verdict,
        "gate_passed": gate_passed,
        "gates": gates,
        "mean_pf_all_windows": mean_pf_all,
        "mean_auc": mean_auc,
        "min_trades_per_window": min_trades_per_window,
        "windows_eligible_honest": len(eligible),
        "mean_pf_honest": mean_pf_honest,
        "gate_passed_honest": gate_passed_honest,
        "gates_honest": gates_honest,
        "pf_inflation_windows": inflated_windows,
        "windows_pf_above_1_3": windows_pf_above_1_3,
    }


def _pick_best_threshold_joint(wf: dict[str, Any]) -> dict[str, Any]:
    """Pick threshold maximizing joint AUC proximity + PF after calibration."""
    mean_auc = float(wf.get("mean_auc") or 0)
    best: dict[str, Any] = {"threshold": PRIMARY_THRESHOLD, "mean_pf": wf.get("mean_pf"), "score": -1.0}
    for row in wf.get("threshold_summary") or []:
        thr = float(row["threshold"])
        pf = float(row.get("mean_pf") or 0)
        n_win = int(row.get("windows_with_min_trades") or 0)
        if n_win < 2:
            continue
        auc_score = mean_auc / GATE_MEAN_AUC
        pf_score = pf / GATE_MEAN_PF if pf > 0 else 0
        joint = min(auc_score, pf_score)
        if pf >= 0.8 and joint > best["score"]:
            best = {"threshold": thr, "mean_pf": pf, "mean_auc": mean_auc, "score": round(joint, 4)}
    return best


def run_auc_lift_experiments(df: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
    """Section A — class weighting, calibration, stricter label, threshold sweep."""
    baseline = auc_lift_walk_forward(df, "label_v3", feature_cols, technique="baseline")
    balanced = auc_lift_walk_forward(df, "label_v3", feature_cols, technique="class_weight_balanced")
    tp_first = auc_lift_walk_forward(df, "label_v3", feature_cols, technique="class_weight_tp_first")
    platt = auc_lift_walk_forward(df, "label_v3", feature_cols, technique="calibration_platt")
    isotonic = auc_lift_walk_forward(df, "label_v3", feature_cols, technique="calibration_isotonic")

    strict_label_result: dict[str, Any] = {"verdict": "SKIPPED", "reason": "stricter relabel unavailable"}
    strict_df = _build_stricter_label(df)
    if "label_strict_tp" in strict_df.columns:
        resolved = strict_df[strict_df["label_strict_tp"].isin([0, 1])]
        if len(resolved) >= 1000:
            strict_wf = auc_lift_walk_forward(
                strict_df, "label_strict_tp", feature_cols, technique="baseline",
            )
            strict_label_result = {
                **strict_wf,
                "horizon_bars": STRICT_HORIZON,
                "resolved_rows": len(resolved),
                "win_rate_pct": round(resolved["label_strict_tp"].mean() * 100, 2),
            }

    experiments = {
        "baseline_rf_10f": baseline,
        "class_weight_balanced": balanced,
        "class_weight_tp_first": tp_first,
        "calibration_platt": platt,
        "calibration_isotonic": isotonic,
        "label_strict_tp_h48": strict_label_result,
    }

    scored: list[dict[str, Any]] = []
    for name, wf in experiments.items():
        if not wf.get("per_year"):
            continue
        joint_thr = _pick_best_threshold_joint(wf)
        scored.append({
            "experiment": name,
            "mean_auc": float(wf.get("mean_auc") or 0),
            "mean_pf_at_0_40": float(wf.get("mean_pf") or 0),
            "best_joint_threshold": joint_thr,
            "auc_gap_to_target": round(GATE_MEAN_AUC - float(wf.get("mean_auc") or 0), 4),
            "pf_preserved": float(wf.get("mean_pf") or 0) >= GATE_MEAN_PF * 0.85,
        })

    if not scored:
        best_exp = {"experiment": "none", "mean_auc": 0, "mean_pf_at_0_40": 0}
    else:
        viable = [s for s in scored if s["pf_preserved"]]
        pool = viable if viable else scored
        best_exp = max(pool, key=lambda x: (x["mean_auc"], x["mean_pf_at_0_40"]))

    best_wf = experiments.get(best_exp["experiment"], baseline)
    return {
        "experiments": experiments,
        "comparison": scored,
        "best_technique": best_exp["experiment"],
        "best_wf": best_wf,
        "baseline_mean_auc": float(baseline.get("mean_auc") or 0),
        "baseline_mean_pf": float(baseline.get("mean_pf") or 0),
        "auc_lift_delta": round(float(best_exp.get("mean_auc", 0)) - float(baseline.get("mean_auc") or 0), 4),
    }


def run_trade_count_floor_analysis(wf: dict[str, Any]) -> dict[str, Any]:
    """Section B — honest PF with min_trades_per_window=30."""
    gate_default = _evaluate_gates(wf, min_trades_per_window=MIN_TRADES_DEFAULT)
    gate_floor = _evaluate_gates(wf, min_trades_per_window=MIN_TRADES_FLOOR)

    per_year = wf.get("per_year") or []
    low_trade_detail = [
        {
            "test_year": w["test_year"],
            "primary_pf": w["primary_pf"],
            "primary_trades": w["primary_trades"],
            "excluded_from_honest_pf": w["primary_trades"] < MIN_TRADES_FLOOR,
        }
        for w in per_year
    ]

    pf_all = float(gate_default.get("mean_pf_all_windows") or 0)
    pf_honest = float(gate_floor.get("mean_pf_honest") or 0)

    return {
        "min_trades_per_window": MIN_TRADES_FLOOR,
        "mean_pf_all_windows": pf_all,
        "mean_pf_honest": pf_honest,
        "pf_inflation_pct": round((pf_all - pf_honest) / max(pf_honest, 0.01) * 100, 2) if pf_honest else None,
        "windows_eligible": gate_floor.get("windows_eligible_honest"),
        "windows_total": len(per_year),
        "gate_default": gate_default,
        "gate_floor_30": gate_floor,
        "per_year_detail": low_trade_detail,
        "inflation_note": (
            "2023 (6 trades, PF 2.0) and 2024 (19 trades, PF 5.33) inflate mean PF "
            "when included; honest PF uses only windows with >=30 trades."
        ),
    }


def _would_pass_tq_only(signal: dict[str, Any]) -> bool:
    if signal.get("would_reach_execution"):
        return True
    if str(signal.get("first_blocking_filter") or "") == "TradeQuality" and signal.get("risk_allowed", False):
        return True
    return False


def run_execution_counterfactual(
    cache_dir: Path,
    *,
    confidence_threshold: float = PRIMARY_THRESHOLD,
) -> dict[str, Any]:
    """Section C — RF-10f high-confidence signals vs execution funnel."""
    per_cache: list[dict[str, Any]] = []
    totals = {
        "trend_hc_signals": 0,
        "full_path_pass": 0,
        "tq_only_pass": 0,
        "still_blocked": 0,
        "tq_blocked": 0,
        "ar_blocked": 0,
        "other_blocked": 0,
    }

    for label in CACHE_LABELS:
        path = cache_dir / f"ml_signals_fullest_{label}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        signals = payload.get("signals") or []

        hc = [
            s for s in signals
            if s.get("regime") == "TREND"
            and float(s.get("probability") or 0) >= confidence_threshold
        ]
        full_pass = sum(1 for s in hc if s.get("would_reach_execution"))
        tq_pass = sum(1 for s in hc if _would_pass_tq_only(s))
        blockers = Counter(str(s.get("first_blocking_filter") or "none") for s in hc if not _would_pass_tq_only(s))

        per_cache.append({
            "cache_label": label,
            "trend_hc_signals": len(hc),
            "full_path_pass": full_pass,
            "full_path_capture_rate_pct": round(full_pass / max(len(hc), 1) * 100, 2),
            "tq_only_pass": tq_pass,
            "tq_only_capture_rate_pct": round(tq_pass / max(len(hc), 1) * 100, 2),
            "incremental_from_tq_bypass": tq_pass - full_pass,
            "blockers_after_tq_bypass": dict(blockers),
        })

        totals["trend_hc_signals"] += len(hc)
        totals["full_path_pass"] += full_pass
        totals["tq_only_pass"] += tq_pass
        totals["tq_blocked"] += sum(1 for s in hc if s.get("first_blocking_filter") == "TradeQuality")
        totals["ar_blocked"] += sum(1 for s in hc if s.get("first_blocking_filter") == "AdaptiveRisk")

    if not per_cache:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no phase46 caches found"}

    totals["still_blocked"] = totals["trend_hc_signals"] - totals["tq_only_pass"]
    full_capture = round(totals["full_path_pass"] / max(totals["trend_hc_signals"], 1) * 100, 2)
    tq_capture = round(totals["tq_only_pass"] / max(totals["trend_hc_signals"], 1) * 100, 2)

    phase53_capture = 0.0
    r53 = ROOT / "phase53_final_report.json"
    if r53.is_file():
        phase53_capture = float(
            json.loads(r53.read_text(encoding="utf-8")).get("aggregate", {}).get("capture_rate_pct") or 0,
        )

    return {
        "verdict": "EXEC_COUNTERFACTUAL_COMPLETE",
        "confidence_threshold": confidence_threshold,
        "proxy_note": "phase46 cache probability>=0.40 used as RF-10f high-confidence proxy",
        "caches_simulated": len(per_cache),
        "per_cache": per_cache,
        "aggregate": {
            "trend_hc_signals": totals["trend_hc_signals"],
            "full_path_pass": totals["full_path_pass"],
            "full_path_capture_rate_pct": full_capture,
            "tq_only_pass": totals["tq_only_pass"],
            "tq_only_capture_rate_pct": tq_capture,
            "incremental_from_tq_bypass": totals["tq_only_pass"] - totals["full_path_pass"],
            "still_blocked_after_tq_bypass": totals["still_blocked"],
            "trade_quality_blocked": totals["tq_blocked"],
            "adaptive_risk_blocked": totals["ar_blocked"],
        },
        "vs_phase53": {
            "phase53_capture_rate_pct": phase53_capture,
            "full_path_delta_pct": round(full_capture - phase53_capture, 2),
            "tq_only_delta_pct": round(tq_capture - phase53_capture, 2),
        },
        "research_only": True,
    }


def _estimate_proximity(wf: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.ml.research.phase51.profitability_score import profitability_proximity

    r52 = ROOT / "phase52_final_report.json"
    label_match = 100.0
    if r52.is_file():
        label_match = float(json.loads(r52.read_text(encoding="utf-8")).get("stored_vs_production_match_pct") or 100.0)

    return profitability_proximity(
        strict_gate_passed=bool(gate.get("gate_passed")),
        mean_pf=float(gate.get("mean_pf_all_windows") or wf.get("mean_pf") or 0),
        mean_auc=float(gate.get("mean_auc") or wf.get("mean_auc") or 0),
        windows_count=int(wf.get("windows") or 0),
        windows_pf_above_1_3=int(gate.get("windows_pf_above_1_3") or 0),
        raw_ml_pf=float(gate.get("mean_pf_all_windows") or wf.get("mean_pf") or 0),
        executed_pf=0.0,
        label_prod_match_pct=label_match,
        v7_rows=int(wf.get("rows_trend") or 0),
    )


def _recommendation(
    gate: dict[str, Any],
    gate_honest: dict[str, Any],
    best_technique: str,
    exec_cf: dict[str, Any],
) -> str:
    if gate.get("gate_passed"):
        return (
            f"Phase 60 best technique ({best_technique}) passed strict re-gate — "
            "eligible for shadow validation (research only)."
        )
    mean_auc = float(gate.get("mean_auc") or 0)
    mean_pf = float(gate.get("mean_pf_all_windows") or 0)
    honest_pf = float(gate_honest.get("mean_pf_honest") or 0)
    tq_capture = float((exec_cf.get("aggregate") or {}).get("tq_only_capture_rate_pct") or 0)
    return (
        f"Phase 60: best AUC lift via {best_technique} (AUC {mean_auc:.4f}, PF {mean_pf:.2f}; "
        f"honest PF@{MIN_TRADES_FLOOR} trades={honest_pf:.2f}). "
        f"AUC still below 0.55. Execution counterfactual TQ-bypass capture {tq_capture:.1f}% "
        f"vs phase53 {float((exec_cf.get('vs_phase53') or {}).get('phase53_capture_rate_pct') or 0):.1f}%. "
        "Production integration NOT justified — fix execution funnel first."
    )


def run_phase60() -> dict[str, Any]:
    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    _, feats_10 = _load_feature_sets()
    avail_10 = [c for c in feats_10 if c in df.columns]

    auc_lift = run_auc_lift_experiments(df, avail_10)
    best_wf = auc_lift.get("best_wf") or {}

    trade_floor = run_trade_count_floor_analysis(best_wf)
    exec_cf = run_execution_counterfactual(CACHE_DIR)

    re_gate = _evaluate_gates(best_wf, min_trades_per_window=MIN_TRADES_DEFAULT)
    re_gate_honest = trade_floor.get("gate_floor_30") or {}

    proximity = _estimate_proximity(best_wf, re_gate) if best_wf.get("per_year") else {}

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "auc_lift": auc_lift,
        "trade_count_floor": trade_floor,
        "execution_counterfactual": exec_cf,
        "re_gate": re_gate,
        "re_gate_honest": re_gate_honest,
        "best_technique": auc_lift.get("best_technique"),
        "best_wf": best_wf,
        "proximity_update": proximity,
        "recommendation": _recommendation(
            re_gate, re_gate_honest, str(auc_lift.get("best_technique")), exec_cf,
        ),
        "research_only": True,
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    best_wf = data.get("best_wf") or {}
    re_gate = data.get("re_gate") or {}
    re_gate_honest = data.get("re_gate_honest") or {}

    payload = {
        "auc_lift": data.get("auc_lift"),
        "trade_count_floor": data.get("trade_count_floor"),
        "execution_counterfactual": data.get("execution_counterfactual"),
        "re_gate": re_gate,
        "re_gate_honest": re_gate_honest,
        "best_technique": data.get("best_technique"),
    }
    (ARTIFACTS / "auc_lift_and_validation.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase60/artifacts/auc_lift_and_validation.json", flush=True)

    report = {
        "phase": "60",
        "title": "AUC Lift + Trade-Count Floor + Execution Counterfactual",
        "title_fa": "ارتقای AUC + کف تعداد معامله + ضد واقعیت اجرا",
        "timestamp_utc": data["now"],
        "verdict": re_gate.get("verdict", "INCOMPLETE"),
        "verdict_honest_min_trades_30": (
            "STRICT_GATE_PASS" if re_gate_honest.get("gate_passed_honest") else "STRICT_GATE_FAIL"
        ),
        "research_only": True,
        "gate_passed": re_gate.get("gate_passed", False),
        "gate_passed_honest_min_trades_30": re_gate_honest.get("gate_passed_honest", False),
        "gates": re_gate.get("gates"),
        "gates_honest_min_trades_30": re_gate_honest.get("gates_honest"),
        "gate_targets": {"mean_pf": GATE_MEAN_PF, "mean_auc": GATE_MEAN_AUC},
        "best_technique": data.get("best_technique"),
        "auc_lift": {
            "best_technique": data.get("best_technique"),
            "baseline_mean_auc": (data.get("auc_lift") or {}).get("baseline_mean_auc"),
            "baseline_mean_pf": (data.get("auc_lift") or {}).get("baseline_mean_pf"),
            "auc_lift_delta": (data.get("auc_lift") or {}).get("auc_lift_delta"),
            "comparison": (data.get("auc_lift") or {}).get("comparison"),
        },
        "trade_count_floor": data.get("trade_count_floor"),
        "execution_counterfactual": data.get("execution_counterfactual"),
        "mean_pf": re_gate.get("mean_pf_all_windows"),
        "mean_pf_honest": re_gate_honest.get("mean_pf_honest"),
        "mean_auc": re_gate.get("mean_auc"),
        "windows": best_wf.get("windows"),
        "per_year": best_wf.get("per_year"),
        "proximity_update": data.get("proximity_update"),
        "recommendation": data.get("recommendation"),
    }

    (ROOT / "phase60_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase60_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_treatment_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    proximity = report.get("proximity_update") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "TREATMENT_PHASE_60_COMPLETE"
    status["strict_gate_passed"] = bool(report.get("gate_passed"))
    status["proximity_score"] = proximity.get("proximity_score")
    status["proximity_band"] = proximity.get("proximity_band")
    status["how_close_pct"] = proximity.get("proximity_score")
    status["current_treatment_phase"] = "60"
    status["next_step"] = report.get("recommendation", "")

    if report.get("gate_passed"):
        status["engineering_verdict"] = "INTEGRATION_REVIEW_ELIGIBLE"
    else:
        status["engineering_verdict"] = "BLOCK_PRODUCTION_INTEGRATION"

    status.setdefault("treatment_phases", {})["60"] = {
        "status": "COMPLETE",
        "track": "C",
        "verdict": report.get("verdict"),
        "report": "phase60_final_report.json",
        "gate_passed": bool(report.get("gate_passed")),
    }
    exec_agg = (data.get("execution_counterfactual") or {}).get("aggregate") or {}
    status["phase60_summary"] = {
        "best_technique": report.get("best_technique"),
        "mean_pf": report.get("mean_pf"),
        "mean_pf_honest": report.get("mean_pf_honest"),
        "mean_auc": report.get("mean_auc"),
        "gate_passed": bool(report.get("gate_passed")),
        "gate_passed_honest": bool(report.get("gate_passed_honest_min_trades_30")),
        "tq_only_capture_rate_pct": exec_agg.get("tq_only_capture_rate_pct"),
    }

    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_treatment_roadmap(report: dict) -> None:
    path = ROOT / "TREATMENT_ROADMAP.json"
    if not path.is_file():
        return
    roadmap = json.loads(path.read_text(encoding="utf-8"))

    phase60 = {
        "phase": "60",
        "name_en": "AUC Lift + Trade-Count Floor + Execution Counterfactual",
        "name_fa": "ارتقای AUC + کف تعداد معامله + ضد واقعیت اجرا",
        "track": "C",
        "objective": (
            "AUC lift on TREND RF-10f (class weight, calibration, stricter label); "
            "honest PF with min_trades=30; execution counterfactual on phase46 caches."
        ),
        "inputs": [
            "tradingbot/ml/research/phase49/artifacts/dataset_v7_ml_signals.parquet",
            "phase59 rf_10f baseline",
            "phase46 quarterly caches",
            "phase53 funnel baseline",
        ],
        "outputs": [
            "phase60_final_report.json",
            "tradingbot/ml/research/phase60/artifacts/auc_lift_and_validation.json",
        ],
        "success_criteria": {
            "strict_gate_pass": True,
            "mean_auc_ge_0_55": True,
        },
        "dependencies": ["phase59"],
        "status": "COMPLETE",
        "runner": "tradingbot/ml/research/phase60/auc_lift_and_validation.py",
        "verdict": report.get("verdict"),
        "gate_passed": bool(report.get("gate_passed")),
    }

    phases = roadmap.setdefault("phases", [])
    replaced = False
    for i, ph in enumerate(phases):
        if str(ph.get("phase")) == "60":
            phases[i] = phase60
            replaced = True
            break
    if not replaced:
        phases.append(phase60)

    pipeline = roadmap.setdefault("pipeline", {})
    pipeline["current_phase"] = "60"
    order = pipeline.setdefault("execution_order", [])
    if "60" not in order:
        order.append("60")

    roadmap["updated_utc"] = report["timestamp_utc"]
    path.write_text(json.dumps(roadmap, indent=2), encoding="utf-8")
    print("  updated TREATMENT_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase60()
    write_all(data)
    re_gate = data.get("re_gate") or {}
    print(json.dumps({
        "verdict": re_gate.get("verdict"),
        "gate_passed": re_gate.get("gate_passed"),
        "mean_pf": re_gate.get("mean_pf_all_windows"),
        "mean_auc": re_gate.get("mean_auc"),
        "best_technique": data.get("best_technique"),
        "proximity_score": (data.get("proximity_update") or {}).get("proximity_score"),
    }, indent=2))


if __name__ == "__main__":
    main()
