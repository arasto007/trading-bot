"""L4-prep — v8 enriched dataset regime ML test vs v7 baseline (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.phase50.strict_walk_forward import _pf
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

ROOT = Path(__file__).resolve().parents[4]
V8_PATH = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_enriched.parquet"
REPORT_PATH = ROOT / "live_l4_v8_regime_ml_report.json"

PRIMARY_THRESHOLD = 0.40
MIN_TRADES_HONEST = 30
WF_YEARS = (2022, 2023, 2024, 2025, 2026)
REGIMES = ("TREND", "RANGE", "VOLATILE")

V7_BASELINE_FEATURES = [
    "tick_volume_proxy",
    "atr_14",
    "realized_vol_20",
    "rsi_14",
    "macd_histogram",
    "ema200_distance",
    "range_pct",
    "bar_spread_pct",
    "ml_confidence",
    "momentum_5",
]

V8_EXTRA_FEATURES = [
    "hour_of_day",
    "day_of_week",
    "session_london",
    "session_new_york",
    "session_asia",
    "session_off_hours",
    "atr_percentile",
    "spread_proxy",
    "ema200_distance_computed",
    "rsi_14_computed",
    "atr_14_computed",
    "trend_strength",
    "volatility_regime",
    "ema50_slope",
    "roc_10",
    "stoch_k",
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "bos_state",
    "liquidity_sweep",
]

V7_BASELINE_REFERENCE = {
    "source": "phase58_final_report.json (TREND-only RF)",
    "mean_auc": 0.5138,
    "mean_pf_at_threshold_0_40": 0.8139,
    "mean_pf_honest_min_trades_30": 0.5676,
    "primary_threshold": 0.4,
    "windows": 5,
    "regime": "TREND",
    "features_count": 5,
}


def _available_features(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    out: list[str] = []
    for col in candidates:
        if col not in df.columns:
            continue
        if df[col].dtype not in ("float64", "float32", "int64", "int32", "int8", "int16", "uint8"):
            continue
        if df[col].notna().sum() < 100:
            continue
        out.append(col)
    return out


def _v8_feature_set(df: pd.DataFrame) -> list[str]:
    v7 = _available_features(df, V7_BASELINE_FEATURES)
    extra = _available_features(df, V8_EXTRA_FEATURES)
    merged: list[str] = []
    for col in v7 + extra:
        if col not in merged:
            merged.append(col)
    return merged


def _regime_walk_forward(
    df: pd.DataFrame,
    *,
    regime: str | None,
    feature_cols: list[str],
    label_col: str = "label_v3",
    test_years: tuple[int, ...] = WF_YEARS,
    threshold: float = PRIMARY_THRESHOLD,
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    work = df[df[label_col].isin([0, 1])].copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    if regime is not None:
        if "regime" not in work.columns:
            return {"verdict": "NO_REGIME_COLUMN", "regime": regime}
        work = work[work["regime"].astype(str).str.upper() == regime.upper()]
    if work.empty or len(feature_cols) == 0:
        return {"verdict": "INSUFFICIENT_DATA", "regime": regime, "rows": len(work)}

    windows: list[dict[str, Any]] = []
    for test_year in test_years:
        tr = work[work["timestamp"].dt.year < test_year]
        te = work[work["timestamp"].dt.year == test_year]
        if len(tr) < min_train_rows or len(te) < min_test_rows:
            continue

        X_tr = tr[feature_cols].astype(float).fillna(0)
        y_tr = tr[label_col].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0)
        y_te = te[label_col].astype(int).values

        scaler = StandardScaler()
        model = create_trend_ml_model("random_forest", seed=seed)
        model.fit(scaler.fit_transform(X_tr), y_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]

        try:
            auc = round(float(roc_auc_score(y_te, proba)), 4)
        except ValueError:
            auc = 0.5

        primary = {"threshold": threshold, **_pf(y_te, proba, threshold)}
        honest = primary if primary["trades"] >= MIN_TRADES_HONEST else {"pf": 0.0, "trades": primary["trades"], "win_rate": primary["win_rate"]}

        windows.append(
            {
                "test_year": int(test_year),
                "train_rows": len(tr),
                "test_rows": len(te),
                "auc": auc,
                "primary_threshold": threshold,
                "primary_pf": primary["pf"],
                "primary_trades": primary["trades"],
                "primary_win_rate": primary["win_rate"],
                "honest_pf_min_trades_30": honest["pf"] if primary["trades"] >= MIN_TRADES_HONEST else None,
                "meets_min_trades_30": primary["trades"] >= MIN_TRADES_HONEST,
            }
        )

    if len(windows) < 3:
        return {
            "verdict": "INSUFFICIENT_WINDOWS",
            "regime": regime,
            "windows_found": len(windows),
            "walk_forward_windows": windows,
        }

    pfs = [float(w["primary_pf"]) for w in windows]
    honest_pfs = [float(w["honest_pf_min_trades_30"]) for w in windows if w["honest_pf_min_trades_30"] is not None]
    aucs = [float(w["auc"]) for w in windows]
    mean_pf = round(float(np.mean(pfs)), 4)
    mean_auc = round(float(np.mean(aucs)), 4)
    mean_pf_honest = round(float(np.mean(honest_pfs)), 4) if honest_pfs else 0.0
    windows_honest = len(honest_pfs)

    improved_auc = mean_auc > V7_BASELINE_REFERENCE["mean_auc"]
    improved_pf = mean_pf > V7_BASELINE_REFERENCE["mean_pf_at_threshold_0_40"]
    improved_pf_honest = mean_pf_honest > V7_BASELINE_REFERENCE["mean_pf_honest_min_trades_30"]

    return {
        "verdict": "WF_COMPLETE",
        "regime": regime,
        "feature_count": len(feature_cols),
        "features": feature_cols,
        "rows_total": len(work),
        "walk_forward_windows": windows,
        "windows": len(windows),
        "primary_threshold": threshold,
        "mean_auc": mean_auc,
        "mean_pf_at_threshold": mean_pf,
        "mean_pf_honest_min_trades_30": mean_pf_honest,
        "windows_with_min_trades_30": windows_honest,
        "vs_v7_baseline": {
            "delta_auc": round(mean_auc - V7_BASELINE_REFERENCE["mean_auc"], 4),
            "delta_pf": round(mean_pf - V7_BASELINE_REFERENCE["mean_pf_at_threshold_0_40"], 4),
            "delta_pf_honest_30": round(mean_pf_honest - V7_BASELINE_REFERENCE["mean_pf_honest_min_trades_30"], 4),
            "improved_auc": improved_auc,
            "improved_pf": improved_pf,
            "improved_pf_honest_30": improved_pf_honest,
            "any_improvement": improved_auc or improved_pf or improved_pf_honest,
        },
    }


def run_v8_regime_ml_test(
    *,
    v8_path: Path | None = None,
    regimes: tuple[str, ...] = REGIMES,
) -> dict[str, Any]:
    path = v8_path or V8_PATH
    if not path.is_file():
        return {"verdict": "V8_DATASET_MISSING", "path": str(path)}

    print(f"L4prep: loading v8 dataset from {path} ...", flush=True)
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    labeled = df[df["label_v3"].isin([0, 1])].copy() if "label_v3" in df.columns else pd.DataFrame()

    v7_feats = _available_features(labeled, V7_BASELINE_FEATURES)
    v8_feats = _v8_feature_set(labeled)

    print(f"L4prep: labeled rows={len(labeled)} v7_feats={len(v7_feats)} v8_feats={len(v8_feats)}", flush=True)

    regime_results: list[dict[str, Any]] = []
    for regime in regimes:
        print(f"L4prep: walk-forward regime={regime} ...", flush=True)
        v8_result = _regime_walk_forward(labeled, regime=regime, feature_cols=v8_feats)
        v7_on_v8 = _regime_walk_forward(labeled, regime=regime, feature_cols=v7_feats)
        regime_results.append(
            {
                "regime": regime,
                "v8_expanded_rf": v8_result,
                "v7_features_on_v8_rows": v7_on_v8,
            }
        )
        if v8_result.get("verdict") == "WF_COMPLETE":
            print(
                f"  {regime} v8: AUC={v8_result['mean_auc']} PF@0.40={v8_result['mean_pf_at_threshold']} "
                f"honestPF30={v8_result['mean_pf_honest_min_trades_30']}",
                flush=True,
            )

    all_v8 = _regime_walk_forward(labeled, regime=None, feature_cols=v8_feats)
    all_v7 = _regime_walk_forward(labeled, regime=None, feature_cols=v7_feats)

    best_regime = None
    best_delta_auc = -999.0
    for item in regime_results:
        v8 = item.get("v8_expanded_rf", {})
        if v8.get("verdict") != "WF_COMPLETE":
            continue
        delta = float(v8.get("vs_v7_baseline", {}).get("delta_auc", -999))
        if delta > best_delta_auc:
            best_delta_auc = delta
            best_regime = item["regime"]

    any_improvement = any(
        item.get("v8_expanded_rf", {}).get("vs_v7_baseline", {}).get("any_improvement", False)
        for item in regime_results
    )
    any_improved_auc = any(
        item.get("v8_expanded_rf", {}).get("vs_v7_baseline", {}).get("improved_auc", False)
        for item in regime_results
    )
    any_improved_pf_honest = any(
        item.get("v8_expanded_rf", {}).get("vs_v7_baseline", {}).get("improved_pf_honest_30", False)
        for item in regime_results
    )

    gate_pass = any_improved_auc and any_improved_pf_honest

    return {
        "phase": "L4prep",
        "title": "v8 Regime ML Test",
        "title_fa": "تست ML رژیم v8",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "IMPROVEMENT_FOUND" if any_improvement else "NO_IMPROVEMENT_VS_V7",
        "gate_passed": gate_pass,
        "research_only": True,
        "dataset": {
            "path": str(path),
            "rows_total": len(df),
            "rows_labeled": len(labeled),
            "v7_features_available": v7_feats,
            "v8_features_available": v8_feats,
            "v8_feature_count": len(v8_feats),
        },
        "methodology": {
            "model": "random_forest",
            "walk_forward_years": list(WF_YEARS),
            "primary_threshold": PRIMARY_THRESHOLD,
            "min_trades_honest": MIN_TRADES_HONEST,
            "label_col": "label_v3",
            "regimes_tested": list(regimes),
        },
        "v7_baseline_reference": V7_BASELINE_REFERENCE,
        "per_regime": regime_results,
        "all_rows_combined": {
            "v8_expanded_rf": all_v8,
            "v7_features_on_v8_rows": all_v7,
        },
        "best_regime_by_auc_delta": best_regime,
        "summary": {
            "any_improvement_over_v7": any_improvement,
            "any_improved_auc": any_improved_auc,
            "any_improved_pf_honest_30": any_improved_pf_honest,
            "strict_gate_pass": gate_pass,
        },
        "recommendation_en": (
            "v8 features show improvement — continue L4 on best regime"
            if any_improvement
            else "v8 ML does not beat v7 baseline — edge still missing"
        ),
        "recommendation_fa": (
            "ویژگی‌های v8 بهبود نشان داد — ادامه L4"
            if any_improvement
            else "ML v8 از v7 بهتر نیست — لبه هنوز پیدا نشده"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_v8_regime_ml_test()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
