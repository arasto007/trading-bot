"""Phase 58 — TREND-only RF re-gate on top-5 features (research only)."""

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

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase58" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

PRIMARY_THRESHOLD = 0.40
COMPARISON_THRESHOLDS = [0.35, 0.40, 0.45]
TOP_FEATURES = [
    "tick_volume_proxy",
    "atr_14",
    "realized_vol_20",
    "rsi_14",
    "macd_histogram",
]

GATE_MEAN_PF = 1.3
GATE_MEAN_AUC = 0.55


def _load_top_features() -> list[str]:
    r55 = ROOT / "phase55_final_report.json"
    if r55.is_file():
        payload = json.loads(r55.read_text(encoding="utf-8"))
        feats = payload.get("top_features") or []
        if len(feats) >= 5:
            return list(feats[:5])
    return list(TOP_FEATURES)


def trend_only_strict_walk_forward(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    primary_threshold: float = PRIMARY_THRESHOLD,
    comparison_thresholds: list[float] | None = None,
    model_name: str = "random_forest",
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = 15,
    min_windows: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """Strict walk-forward on TREND subset with fixed-threshold re-gate."""
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

    comparison_thresholds = comparison_thresholds or COMPARISON_THRESHOLDS
    all_thresholds = sorted(set(comparison_thresholds))

    work = df[df[label_col].isin([0, 1])].copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    years = sorted(work["timestamp"].dt.year.unique())

    if len(years) < 2:
        return {"verdict": "INSUFFICIENT_DATA", "years": [int(y) for y in years]}

    per_year: list[dict[str, Any]] = []
    threshold_aggregate: dict[float, list[float]] = {t: [] for t in all_thresholds}

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
        for thr in all_thresholds:
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
            "meets_min_trades": primary["trades"] >= min_test_trades,
            "by_threshold": by_threshold,
        })

    if len(per_year) < min_windows:
        return {
            "verdict": "INSUFFICIENT_WINDOWS",
            "windows_found": len(per_year),
            "min_windows_required": min_windows,
            "per_year": per_year,
        }

    threshold_summary: list[dict[str, Any]] = []
    for thr in all_thresholds:
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

    primary_summary = next(
        (s for s in threshold_summary if s["threshold"] == primary_threshold),
        {},
    )

    return {
        "verdict": verdict,
        "gate_passed": gate_passed,
        "gates": gates,
        "regime": "TREND",
        "model": model_name,
        "features_used": feature_cols,
        "feature_count": len(feature_cols),
        "primary_threshold": primary_threshold,
        "comparison_thresholds": comparison_thresholds,
        "windows": len(per_year),
        "mean_pf": mean_pf,
        "mean_auc": mean_auc,
        "primary_threshold_summary": primary_summary,
        "threshold_summary": threshold_summary,
        "windows_pf_above_1": windows_pf_above_1,
        "windows_pf_above_1_3": windows_pf_above_1_3,
        "per_year": per_year,
        "rows_trend": len(work),
        "gate_targets": {"mean_pf": GATE_MEAN_PF, "mean_auc": GATE_MEAN_AUC},
    }


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


def _recommendation(wf: dict[str, Any]) -> str:
    if wf.get("gate_passed"):
        return (
            "TREND-only RF at threshold 0.40 passed strict re-gate — "
            "eligible for shadow/paper validation (research only, no production deploy)."
        )
    mean_pf = float(wf.get("mean_pf") or 0)
    mean_auc = float(wf.get("mean_auc") or 0)
    if mean_pf >= 1.0:
        return (
            f"TREND-only RF marginal (mean PF {mean_pf:.2f}, AUC {mean_auc:.4f}) — "
            "try ensemble or expanded TREND feature set before execution-path work."
        )
    return (
        f"TREND-only RF re-gate failed (mean PF {mean_pf:.2f}, AUC {mean_auc:.4f}). "
        "Do NOT relax TradeQuality. Next: label horizon tuning or regime-specific features."
    )


def run_phase58() -> dict[str, Any]:
    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    feats = _load_top_features()
    available = [c for c in feats if c in df.columns]
    if len(available) < 3:
        from tradingbot.ml.research.phase36.build_dataset_v3 import feature_columns

        available = feature_columns(df)[:5]

    wf = trend_only_strict_walk_forward(df, "label_v3", available)
    proximity = _estimate_proximity(wf) if wf.get("per_year") else {}

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "walk_forward": wf,
        "proximity_update": proximity,
        "recommendation": _recommendation(wf),
        "research_only": True,
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    wf = data.get("walk_forward") or {}

    (ARTIFACTS / "trend_only_wf.json").write_text(
        json.dumps(wf, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase58/artifacts/trend_only_wf.json", flush=True)

    report = {
        "phase": "58",
        "title": "TREND-only RF Re-gate",
        "title_fa": "بازگشت gate مدل TREND-only",
        "timestamp_utc": data["now"],
        "verdict": wf.get("verdict", "INCOMPLETE"),
        "research_only": True,
        "gate_passed": wf.get("gate_passed", False),
        "gates": wf.get("gates"),
        "gate_targets": wf.get("gate_targets"),
        "model": wf.get("model"),
        "regime": wf.get("regime"),
        "features_used": wf.get("features_used"),
        "primary_threshold": wf.get("primary_threshold"),
        "comparison_thresholds": wf.get("comparison_thresholds"),
        "mean_pf": wf.get("mean_pf"),
        "mean_auc": wf.get("mean_auc"),
        "windows": wf.get("windows"),
        "windows_pf_above_1_3": wf.get("windows_pf_above_1_3"),
        "primary_threshold_summary": wf.get("primary_threshold_summary"),
        "threshold_summary": wf.get("threshold_summary"),
        "per_year": wf.get("per_year"),
        "rows_trend": wf.get("rows_trend"),
        "proximity_update": data.get("proximity_update"),
        "recommendation": data.get("recommendation"),
    }

    (ROOT / "phase58_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase58_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_treatment_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    proximity = report.get("proximity_update") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "TREATMENT_PHASE_58_COMPLETE"
    status["strict_gate_passed"] = bool(report.get("gate_passed"))
    status["proximity_score"] = proximity.get("proximity_score")
    status["proximity_band"] = proximity.get("proximity_band")
    status["how_close_pct"] = proximity.get("proximity_score")
    status["current_treatment_phase"] = "58"
    status["next_step"] = report.get("recommendation", "")

    if report.get("gate_passed"):
        status["engineering_verdict"] = "INTEGRATION_REVIEW_ELIGIBLE"
    else:
        status["engineering_verdict"] = "BLOCK_PRODUCTION_INTEGRATION"

    status.setdefault("treatment_phases", {})["58"] = {
        "status": "COMPLETE",
        "track": "D",
        "verdict": report.get("verdict"),
        "report": "phase58_final_report.json",
        "gate_passed": bool(report.get("gate_passed")),
    }
    status["phase58_summary"] = {
        "mean_pf": report.get("mean_pf"),
        "mean_auc": report.get("mean_auc"),
        "primary_threshold": report.get("primary_threshold"),
        "gate_passed": bool(report.get("gate_passed")),
        "windows_pf_above_1_3": report.get("windows_pf_above_1_3"),
        "rows_trend": report.get("rows_trend"),
    }

    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_treatment_roadmap(report: dict) -> None:
    path = ROOT / "TREATMENT_ROADMAP.json"
    if not path.is_file():
        return
    roadmap = json.loads(path.read_text(encoding="utf-8"))

    for phase in roadmap.get("phases", []):
        if str(phase.get("phase")) == "58":
            phase["status"] = "COMPLETE"
            phase["name_en"] = "TREND-only RF Re-gate"
            phase["name_fa"] = "بازگشت gate مدل TREND-only"
            phase["objective"] = (
                "Train TREND-only RF on top-5 phase55 features; "
                "strict walk-forward re-gate at threshold 0.40."
            )
            phase["inputs"] = [
                "tradingbot/ml/research/phase49/artifacts/dataset_v7_ml_signals.parquet",
                "phase55 top-5 features",
                "phase50/strict_walk_forward.py patterns",
            ]
            phase["outputs"] = [
                "phase58_final_report.json",
                "tradingbot/ml/research/phase58/artifacts/trend_only_wf.json",
            ]
            phase["runner"] = "tradingbot/ml/research/phase58/trend_only_model.py"
            phase["track"] = "D"
            phase["verdict"] = report.get("verdict")
            phase["gate_passed"] = bool(report.get("gate_passed"))
            break

    pipeline = roadmap.setdefault("pipeline", {})
    pipeline["current_phase"] = "58"
    if "58" not in pipeline.get("execution_order", []):
        pipeline.setdefault("execution_order", []).append("58")

    roadmap["updated_utc"] = report["timestamp_utc"]
    path.write_text(json.dumps(roadmap, indent=2), encoding="utf-8")
    print("  updated TREATMENT_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase58()
    write_all(data)
    wf = data.get("walk_forward") or {}
    print(json.dumps({
        "verdict": wf.get("verdict"),
        "gate_passed": wf.get("gate_passed"),
        "mean_pf": wf.get("mean_pf"),
        "mean_auc": wf.get("mean_auc"),
        "primary_threshold": wf.get("primary_threshold"),
        "proximity_score": (data.get("proximity_update") or {}).get("proximity_score"),
    }, indent=2))


if __name__ == "__main__":
    main()
