"""Phase 65 — AUC lift via TREND-specific feature engineering (research only).

Engineer interactions/ratios/lags from v7 columns; compare RF on baseline 10f,
expanded 15-20f, and pruned high-importance sets. Strict 5-window walk-forward
on TREND subset at threshold 0.40 with honest PF@30 trades.
"""

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

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase65" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

PRIMARY_THRESHOLD = 0.40
GATE_MEAN_PF = 1.3
GATE_MEAN_AUC = 0.55
MIN_TRADES_FLOOR = 30
MIN_TRADES_DEFAULT = 15

BASELINE_10F = [
    "tick_volume_proxy",
    "atr_14",
    "realized_vol_20",
    "rsi_14",
    "macd_histogram",
    "ema200_distance",
    "momentum_5",
    "range_pct",
    "bar_spread_pct",
    "ml_confidence",
]

ENGINEERED_FEATURES = [
    "vol_momentum",
    "rsi_atr_ratio",
    "trend_vol_interaction",
    "ema_trend_combo",
    "macd_rsi_spread",
    "volume_vol_ratio",
    "spread_atr_ratio",
    "ml_vol_confidence",
    "range_atr_ratio",
    "momentum_rsi",
    "h4_ema_bias",
    "london_trend_strength",
    "atr_pct_vol",
    "conf_momentum",
    "ema_slope_distance",
    "rsi_14_lag1",
    "momentum_5_lag1",
    "realized_vol_20_lag1",
    "tick_volume_proxy_lag1",
    "macd_histogram_lag1",
]

LAG_SOURCE_COLS = [
    "rsi_14",
    "momentum_5",
    "realized_vol_20",
    "tick_volume_proxy",
    "macd_histogram",
]


def _load_baseline_features() -> list[str]:
    r55 = ROOT / "phase55_final_report.json"
    if r55.is_file():
        feats = list(json.loads(r55.read_text(encoding="utf-8")).get("top_features") or [])
        if len(feats) >= 10:
            return [f for f in feats[:10] if f in BASELINE_10F or True]
    return list(BASELINE_10F)


def _load_trend_df(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    return work.sort_values("timestamp").reset_index(drop=True)


def engineer_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create TREND-specific interactions, ratios, and 1-bar lags."""
    work = _load_trend_df(df)
    eps = 1e-6

    for col in LAG_SOURCE_COLS:
        if col in work.columns:
            work[f"{col}_lag1"] = work[col].astype(float).shift(1)

    if "realized_vol_20" in work.columns and "momentum_5" in work.columns:
        work["vol_momentum"] = work["realized_vol_20"] * work["momentum_5"].abs()

    if "rsi_14" in work.columns and "atr_14" in work.columns:
        work["rsi_atr_ratio"] = work["rsi_14"] / (work["atr_14"] + eps)

    if "trend_strength" in work.columns and "realized_vol_20" in work.columns:
        work["trend_vol_interaction"] = work["trend_strength"] * work["realized_vol_20"]

    if "ema200_distance" in work.columns and "trend_strength" in work.columns:
        work["ema_trend_combo"] = work["ema200_distance"] * work["trend_strength"]

    if "macd_histogram" in work.columns and "rsi_14" in work.columns:
        work["macd_rsi_spread"] = work["macd_histogram"] * (work["rsi_14"] - 50.0) / 50.0

    if "tick_volume_proxy" in work.columns and "realized_vol_20" in work.columns:
        work["volume_vol_ratio"] = work["tick_volume_proxy"] / (work["realized_vol_20"] + eps)

    if "bar_spread_pct" in work.columns and "atr_14" in work.columns:
        work["spread_atr_ratio"] = work["bar_spread_pct"] / (work["atr_14"] + eps)

    if "ml_confidence" in work.columns and "realized_vol_20" in work.columns:
        work["ml_vol_confidence"] = work["ml_confidence"] * work["realized_vol_20"]

    if "range_pct" in work.columns and "atr_14" in work.columns:
        work["range_atr_ratio"] = work["range_pct"] / (work["atr_14"] + eps)

    if "momentum_5" in work.columns and "rsi_14" in work.columns:
        work["momentum_rsi"] = work["momentum_5"] * work["rsi_14"] / 100.0

    if "h4_trend_bias" in work.columns and "ema200_distance" in work.columns:
        work["h4_ema_bias"] = work["h4_trend_bias"] * work["ema200_distance"]

    if "session_london" in work.columns and "trend_strength" in work.columns:
        work["london_trend_strength"] = work["session_london"] * work["trend_strength"]

    if "atr_percentile" in work.columns and "realized_vol_20" in work.columns:
        work["atr_pct_vol"] = work["atr_percentile"] * work["realized_vol_20"] / 100.0

    if "ml_confidence" in work.columns and "momentum_5" in work.columns:
        work["conf_momentum"] = work["ml_confidence"] * work["momentum_5"]

    if "ema50_slope" in work.columns and "ema200_distance" in work.columns:
        work["ema_slope_distance"] = work["ema50_slope"] * work["ema200_distance"]

    return work


def _available_features(df: pd.DataFrame, candidates: list[str]) -> list[str]:
    return [c for c in candidates if c in df.columns]


def rank_feature_importance(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    seed: int = 42,
    train_fraction: float = 0.7,
) -> list[dict[str, Any]]:
    """Chronological RF fit for feature importance ranking."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler

    work = df[df[label_col].isin([0, 1])].copy()
    work = work.sort_values("timestamp")
    split = max(200, int(len(work) * train_fraction))
    if split >= len(work) - 100:
        split = len(work) - 100
    tr = work.iloc[:split]

    X = tr[feature_cols].astype(float).fillna(0)
    y = tr[label_col].astype(int).values
    scaler = StandardScaler()
    model = RandomForestClassifier(
        n_estimators=120, max_depth=6, random_state=seed, min_samples_leaf=10,
    )
    model.fit(scaler.fit_transform(X), y)

    ranked = sorted(
        zip(feature_cols, model.feature_importances_.tolist()),
        key=lambda x: x[1],
        reverse=True,
    )
    return [{"feature": f, "importance": round(float(imp), 6)} for f, imp in ranked]


def _evaluate_gates(
    wf: dict[str, Any],
    *,
    min_trades_per_window: int = MIN_TRADES_DEFAULT,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase60.auc_lift_and_validation import _evaluate_gates

    return _evaluate_gates(wf, min_trades_per_window=min_trades_per_window)


def _run_config(
    df: pd.DataFrame,
    config_id: str,
    feature_cols: list[str],
    *,
    description: str,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase58.trend_only_model import trend_only_strict_walk_forward

    wf = trend_only_strict_walk_forward(
        df,
        "label_v3",
        feature_cols,
        primary_threshold=PRIMARY_THRESHOLD,
    )
    gates_default = _evaluate_gates(wf, min_trades_per_window=MIN_TRADES_DEFAULT)
    gates_honest = _evaluate_gates(wf, min_trades_per_window=MIN_TRADES_FLOOR)

    baseline_auc = 0.5153
    baseline_pf = 1.7343
    mean_auc = float(wf.get("mean_auc") or 0)
    mean_pf = float(wf.get("mean_pf") or 0)

    return {
        "config_id": config_id,
        "description": description,
        "features": feature_cols,
        "feature_count": len(feature_cols),
        "walk_forward": wf,
        "mean_auc": mean_auc,
        "mean_pf": mean_pf,
        "mean_pf_honest": gates_honest.get("mean_pf_honest"),
        "windows_eligible_honest": gates_honest.get("windows_eligible_honest"),
        "gate_passed": bool(wf.get("gate_passed")),
        "gate_passed_honest": bool(gates_honest.get("gate_passed_honest")),
        "gates": wf.get("gates"),
        "gates_honest": gates_honest.get("gates_honest"),
        "verdict": wf.get("verdict"),
        "delta_auc_vs_phase59": round(mean_auc - baseline_auc, 4),
        "delta_pf_vs_phase59": round(mean_pf - baseline_pf, 4),
        "auc_gate_pass": mean_auc >= GATE_MEAN_AUC,
        "honest_pf_gate_pass": float(gates_honest.get("mean_pf_honest") or 0) >= GATE_MEAN_PF,
    }


def _pick_best_config(configs: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [c for c in configs if c.get("walk_forward", {}).get("per_year")]
    if not scored:
        return {"config_id": "none", "mean_auc": 0.0, "mean_pf": 0.0}

    def score(c: dict[str, Any]) -> tuple:
        wf = c.get("walk_forward") or {}
        return (
            bool(c.get("gate_passed")),
            bool(c.get("gate_passed_honest")),
            float(c.get("mean_auc") or 0),
            float(c.get("mean_pf_honest") or 0),
            float(c.get("mean_pf") or 0),
            int(wf.get("windows_pf_above_1_3") or 0),
        )

    return max(scored, key=score)


def _recommendation(best: dict[str, Any], gate_passed: bool) -> dict[str, str]:
    cfg = best.get("config_id", "none")
    auc = float(best.get("mean_auc") or 0)
    pf = float(best.get("mean_pf") or 0)
    honest = float(best.get("mean_pf_honest") or 0)
    delta_auc = float(best.get("delta_auc_vs_phase59") or 0)

    if gate_passed:
        en = (
            f"Phase 65 best config ({cfg}) passed strict AUC gate (AUC {auc:.4f}). "
            f"Carry features to Phase 67 ensemble."
        )
        fa = (
            f"بهترین کانفیگ فاز ۶۵ ({cfg}) gate AUC را پاس کرد (AUC {auc:.4f}). "
            f"ویژگی‌ها را به فاز ۶۷ ببرید."
        )
    elif auc >= 0.52 or delta_auc > 0.01:
        en = (
            f"Phase 65 marginal AUC lift ({cfg}: AUC {auc:.4f}, Δ{delta_auc:+.4f} vs phase59). "
            f"Honest PF@30={honest:.4f}. Proceed Phase 66 label/horizon experiments."
        )
        fa = (
            f"فاز ۶۵ ارتقای جزئی AUC ({cfg}: AUC {auc:.4f}، Δ{delta_auc:+.4f}). "
            f"PF صادق@30={honest:.4f}. فاز ۶۶: آزمایش label/horizon."
        )
    else:
        en = (
            f"Phase 65 feature engineering insufficient (best {cfg}: AUC {auc:.4f}, PF {pf:.4f}). "
            f"Honest PF@30={honest:.4f}. Next: Phase 66 label/horizon sweep."
        )
        fa = (
            f"مهندسی ویژگی فاز ۶۵ کافی نبود (بهترین {cfg}: AUC {auc:.4f}). "
            f"PF صادق@30={honest:.4f}. بعدی: فاز ۶۶."
        )
    return {"en": en, "fa": fa}


def run_phase65() -> dict[str, Any]:
    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    raw = pd.read_parquet(V7_PATH)
    df = engineer_trend_features(raw)

    baseline_feats = _available_features(df, _load_baseline_features())
    engineered_avail = _available_features(df, ENGINEERED_FEATURES)

    expanded_candidates = list(dict.fromkeys(baseline_feats + engineered_avail))
    expanded_feats = expanded_candidates[:20]

    importance = rank_feature_importance(df, "label_v3", expanded_candidates)
    top_importance_feats = [row["feature"] for row in importance[:12]]
    pruned_feats = list(dict.fromkeys(top_importance_feats))

    engineered_created = [f for f in ENGINEERED_FEATURES if f in df.columns]
    feature_engineering = {
        "baseline_10f": baseline_feats,
        "engineered_created": engineered_created,
        "engineered_count": len(engineered_created),
        "expanded_15_20f": expanded_feats,
        "expanded_count": len(expanded_feats),
        "importance_ranking": importance[:20],
        "pruned_high_importance": pruned_feats,
        "pruned_count": len(pruned_feats),
    }

    configs = [
        _run_config(
            df,
            "baseline_rf_10f",
            baseline_feats,
            description="Phase59 baseline 10 features",
        ),
        _run_config(
            df,
            "expanded_rf_15_20f",
            expanded_feats,
            description=f"Baseline + engineered interactions/lags ({len(expanded_feats)} features)",
        ),
        _run_config(
            df,
            "pruned_rf_high_importance",
            pruned_feats,
            description=f"Top-{len(pruned_feats)} by RF importance on expanded set",
        ),
    ]

    best = _pick_best_config(configs)
    best_wf = best.get("walk_forward") or {}
    auc_gate = float(best.get("mean_auc") or 0) >= GATE_MEAN_AUC
    honest_gate = bool(best.get("honest_pf_gate_pass"))
    overall_gate = auc_gate and honest_gate

    if overall_gate:
        verdict = "STRICT_GATE_PASS"
    elif float(best.get("mean_auc") or 0) >= 0.52:
        verdict = "STRICT_GATE_MARGINAL"
    else:
        verdict = "STRICT_GATE_FAIL"

    comparison = [
        {
            "config_id": c["config_id"],
            "feature_count": c["feature_count"],
            "mean_auc": c["mean_auc"],
            "mean_pf": c["mean_pf"],
            "mean_pf_honest": c["mean_pf_honest"],
            "delta_auc_vs_phase59": c["delta_auc_vs_phase59"],
            "auc_gate_pass": c["auc_gate_pass"],
            "honest_pf_gate_pass": c["honest_pf_gate_pass"],
            "verdict": c["verdict"],
        }
        for c in configs
    ]

    rec = _recommendation(best, overall_gate)

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "gate_passed": overall_gate,
        "auc_gate_pass": auc_gate,
        "honest_pf_gate_pass": honest_gate,
        "gate_targets": {"mean_auc": GATE_MEAN_AUC, "honest_pf": GATE_MEAN_PF, "min_trades": MIN_TRADES_FLOOR},
        "feature_engineering": feature_engineering,
        "config_comparison": comparison,
        "configs": {c["config_id"]: c for c in configs},
        "best_config": {
            "config_id": best.get("config_id"),
            "features": best.get("features"),
            "feature_count": best.get("feature_count"),
            "mean_auc": best.get("mean_auc"),
            "mean_pf": best.get("mean_pf"),
            "mean_pf_honest": best.get("mean_pf_honest"),
            "delta_auc_vs_phase59": best.get("delta_auc_vs_phase59"),
            "primary_threshold": PRIMARY_THRESHOLD,
            "for_phase_67_68": {
                "config_id": best.get("config_id"),
                "features": best.get("features"),
                "threshold": PRIMARY_THRESHOLD,
                "label_col": "label_v3",
                "model": "random_forest",
            },
        },
        "re_gate": {
            "mean_auc": best.get("mean_auc"),
            "mean_pf": best.get("mean_pf"),
            "mean_pf_honest": best.get("mean_pf_honest"),
            "windows": best_wf.get("windows"),
            "per_year": best_wf.get("per_year"),
            "gates": best.get("gates"),
            "gates_honest": best.get("gates_honest"),
        },
        "recommendation_en": rec["en"],
        "recommendation_fa": rec["fa"],
        "next_phase": "66",
        "research_only": True,
        "rows_trend": int((df["label_v3"].isin([0, 1])).sum()),
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    artifact = {
        "feature_engineering": data.get("feature_engineering"),
        "config_comparison": data.get("config_comparison"),
        "best_config": data.get("best_config"),
        "re_gate": data.get("re_gate"),
    }
    (ARTIFACTS / "auc_feature_lift.json").write_text(
        json.dumps(artifact, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase65/artifacts/auc_feature_lift.json", flush=True)

    best = data.get("best_config") or {}
    report = {
        "phase": "65",
        "title": "AUC Lift — TREND Feature Engineering",
        "title_fa": "ارتقای AUC — مهندسی ویژگی TREND",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "gate_passed": data.get("gate_passed"),
        "auc_gate_pass": data.get("auc_gate_pass"),
        "honest_pf_gate_pass": data.get("honest_pf_gate_pass"),
        "gate_targets": data.get("gate_targets"),
        "feature_engineering": data.get("feature_engineering"),
        "config_comparison": data.get("config_comparison"),
        "best_config": best,
        "mean_auc": best.get("mean_auc"),
        "mean_pf": best.get("mean_pf"),
        "mean_pf_honest": best.get("mean_pf_honest"),
        "delta_auc_vs_phase59": best.get("delta_auc_vs_phase59"),
        "primary_threshold": PRIMARY_THRESHOLD,
        "re_gate": data.get("re_gate"),
        "for_phase_67_68": best.get("for_phase_67_68"),
        "recommendation_en": data.get("recommendation_en"),
        "recommendation_fa": data.get("recommendation_fa"),
        "next_phase": data.get("next_phase"),
        "rows_trend": data.get("rows_trend"),
    }
    (ROOT / "phase65_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase65_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    best = data.get("best_config") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_65_COMPLETE"
    status["current_treatment_phase"] = "65"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["65"] = {
        "status": "COMPLETE",
        "track": "M",
        "verdict": report.get("verdict"),
        "report": "phase65_final_report.json",
        "gate_passed": bool(report.get("gate_passed")),
    }
    status["phase65_summary"] = {
        "best_config": best.get("config_id"),
        "feature_count": best.get("feature_count"),
        "engineered_features_created": (data.get("feature_engineering") or {}).get("engineered_count"),
        "mean_auc": best.get("mean_auc"),
        "mean_pf": best.get("mean_pf"),
        "mean_pf_honest": best.get("mean_pf_honest"),
        "delta_auc_vs_phase59": best.get("delta_auc_vs_phase59"),
        "auc_gate_pass": bool(report.get("auc_gate_pass")),
        "honest_pf_gate_pass": bool(report.get("honest_pf_gate_pass")),
        "for_phase_67_68": best.get("for_phase_67_68"),
    }
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_fix_roadmap(report: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))
    for ph in fix.get("phases", []):
        if str(ph.get("phase")) == "65":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "66"
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase65()
    write_all(data)
    best = data.get("best_config") or {}
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "gate_passed": data.get("gate_passed"),
                "best_config": best.get("config_id"),
                "mean_auc": best.get("mean_auc"),
                "mean_pf": best.get("mean_pf"),
                "mean_pf_honest": best.get("mean_pf_honest"),
                "delta_auc_vs_phase59": best.get("delta_auc_vs_phase59"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
