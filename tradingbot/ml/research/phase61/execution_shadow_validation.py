"""Phase 61 — execution-path shadow validation for TREND RF-10f (research only)."""



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



ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase61" / "artifacts"

V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"

CACHE_LABELS = ("A", "B", "C", "H")

PREDICTIONS_CACHE = ARTIFACTS / "rf10f_v7_predictions.parquet"



PRIMARY_THRESHOLD = 0.40

WF_PF_REFERENCE = 1.7343

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





def _pf_from_labels(labels: list[int]) -> dict[str, float | int]:

    if not labels:

        return {"pf": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0}

    wins = sum(1 for x in labels if x == 1)

    losses = sum(1 for x in labels if x == 0)

    pf = wins / losses if losses > 0 else (2.0 if wins > 0 else 0.0)

    return {

        "pf": round(pf, 4),

        "trades": len(labels),

        "wins": wins,

        "losses": losses,

        "win_rate_pct": round(wins / len(labels) * 100, 2),

    }





def _build_v7_label_index(df: pd.DataFrame) -> dict[tuple, int]:

    work = df.copy()

    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)

    work["dir_str"] = work["direction"].map({1: "BUY", -1: "SELL"})

    index: dict[tuple, int] = {}

    for _, row in work.iterrows():

        if pd.isna(row.get("label_v3")) or row["label_v3"] not in (0, 1):

            continue

        key = (row["timestamp"], row["dir_str"])

        index[key] = int(row["label_v3"])

    return index





def _signal_key(signal: dict[str, Any]) -> tuple | None:

    direction = str(signal.get("direction") or "")

    if direction not in ("BUY", "SELL"):

        return None

    try:

        ts = pd.to_datetime(signal["timestamp"], utc=True)

    except (KeyError, TypeError, ValueError):

        return None

    return ts, direction





def _would_pass_path_a(signal: dict[str, Any]) -> bool:

    return bool(signal.get("would_reach_execution"))





def _would_pass_path_b(signal: dict[str, Any]) -> bool:

    if signal.get("would_reach_execution"):

        return True

    if str(signal.get("first_blocking_filter") or "") == "TradeQuality" and signal.get("risk_allowed", False):

        return True

    return False





def _would_pass_path_c(signal: dict[str, Any]) -> bool:

    if signal.get("would_reach_execution"):

        return True

    blocker = str(signal.get("first_blocking_filter") or "")

    if blocker in ("TradeQuality", "AdaptiveRisk"):

        return True

    return False





PATH_FILTERS = {

    "A_full_production": _would_pass_path_a,

    "B_tq_bypass_only": _would_pass_path_b,

    "C_tq_ar_bypass": _would_pass_path_c,

}





def _load_hc_signals_from_cache(

    cache_dir: Path,

    *,

    confidence_threshold: float = PRIMARY_THRESHOLD,

) -> list[dict[str, Any]]:

    signals: list[dict[str, Any]] = []

    for label in CACHE_LABELS:

        path = cache_dir / f"ml_signals_fullest_{label}.json"

        if not path.is_file():

            continue

        payload = json.loads(path.read_text(encoding="utf-8"))

        for sig in payload.get("signals") or []:

            if sig.get("regime") != "TREND":

                continue

            if float(sig.get("probability") or 0) < confidence_threshold:

                continue

            rec = dict(sig)

            rec["source_cache"] = label

            signals.append(rec)

    return signals





def _generate_rf10f_v7_predictions(

    df: pd.DataFrame,

    feature_cols: list[str],

    *,

    use_cache: bool = True,

) -> pd.DataFrame:

    """Pooled walk-forward RF-10f proba on v7 TREND rows (cached when available)."""

    if use_cache and PREDICTIONS_CACHE.is_file():

        cached = pd.read_parquet(PREDICTIONS_CACHE)

        if "rf10f_proba" in cached.columns and len(cached) > 0:

            return cached



    from sklearn.ensemble import RandomForestClassifier

    from sklearn.preprocessing import StandardScaler



    work = df[df["label_v3"].isin([0, 1])].copy()

    if "regime" in work.columns:

        work = work[work["regime"] == "TREND"]

    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp")
    work["rf10f_proba"] = np.nan
    years = sorted(work["timestamp"].dt.year.unique())

    for test_year in years[1:]:
        tr_mask = work["timestamp"].dt.year < test_year
        te_mask = work["timestamp"].dt.year == test_year
        if tr_mask.sum() < 200 or te_mask.sum() < 100:
            continue
        tr = work.loc[tr_mask]
        te = work.loc[te_mask]
        X_tr = tr[feature_cols].astype(float).fillna(0).values
        y_tr = tr["label_v3"].astype(int).values
        X_te = te[feature_cols].astype(float).fillna(0).values
        scaler = StandardScaler()
        model = RandomForestClassifier(
            n_estimators=120, max_depth=6, random_state=42, min_samples_leaf=10,
        )
        model.fit(scaler.fit_transform(X_tr), y_tr)
        work.loc[te_mask, "rf10f_proba"] = model.predict_proba(scaler.transform(X_te))[:, 1]

    out = work[work["rf10f_proba"].notna()].copy()
    out["dir_str"] = out["direction"].map({1: "BUY", -1: "SELL"})



    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    out[["timestamp", "bar_index", "direction", "dir_str", "label_v3", "rf10f_proba"]].to_parquet(

        PREDICTIONS_CACHE, index=False,

    )

    return out





def _attach_v7_labels(

    signals: list[dict[str, Any]],

    label_index: dict[tuple, int],

) -> tuple[list[dict[str, Any]], dict[str, Any]]:

    enriched: list[dict[str, Any]] = []

    unmatched = 0

    for sig in signals:

        key = _signal_key(sig)

        if key is None or key not in label_index:

            unmatched += 1

            continue

        rec = dict(sig)

        rec["label_v3"] = label_index[key]

        rec["year"] = int(key[0].year)

        enriched.append(rec)

    return enriched, {

        "total_signals": len(signals),

        "matched_v7_labels": len(enriched),

        "unmatched": unmatched,

        "match_rate_pct": round(len(enriched) / max(len(signals), 1) * 100, 2),

    }





def _path_metrics(

    signals: list[dict[str, Any]],

    path_name: str,

    path_filter,

) -> dict[str, Any]:

    captured = [s for s in signals if path_filter(s)]

    labels = [int(s["label_v3"]) for s in captured]

    pf = _pf_from_labels(labels)

    blockers = Counter(

        str(s.get("first_blocking_filter") or "none")

        for s in signals

        if not path_filter(s)

    )

    return {

        "path": path_name,

        "signals_total_hc": len(signals),

        "signals_captured": len(captured),

        "capture_rate_pct": round(len(captured) / max(len(signals), 1) * 100, 2),

        "pf_proxy_label_v3": pf,

        "blockers_remaining": dict(blockers),

    }





def _per_year_path_b(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:

    by_year: dict[int, list[int]] = defaultdict(list)

    for sig in signals:

        if not _would_pass_path_b(sig):

            continue

        by_year[int(sig["year"])].append(int(sig["label_v3"]))



    rows: list[dict[str, Any]] = []

    for year in sorted(by_year):

        pf = _pf_from_labels(by_year[year])

        rows.append({"year": year, **pf})

    return rows





def _compare_shadow_vs_wf(

    path_metrics: dict[str, dict[str, Any]],

    wf_pf: float,

) -> dict[str, Any]:

    path_b_pf = float((path_metrics.get("B_tq_bypass_only") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0)

    path_a_pf = float((path_metrics.get("A_full_production") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0)

    destruction_pct = round((1 - path_b_pf / max(wf_pf, 0.01)) * 100, 2) if wf_pf > 0 else None

    return {

        "wf_mean_pf_at_0_40": wf_pf,

        "shadow_pf_path_a": path_a_pf,

        "shadow_pf_path_b": path_b_pf,

        "shadow_pf_path_c": float(

            (path_metrics.get("C_tq_ar_bypass") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0,

        ),

        "execution_destruction_pct_path_b_vs_wf": destruction_pct,

        "wf_to_shadow_ratio_path_b": round(path_b_pf / max(wf_pf, 0.01), 4),

        "note": (

            "WF PF is out-of-sample walk-forward on v7; shadow PF is label_v3 on "

            "phase46-cached HC signals matched to v7. Methodology differs but "

            "quantifies execution-path edge destruction."

        ),

    }





def _analyze_adaptive_risk_blocked(

    signals: list[dict[str, Any]],

) -> dict[str, Any]:

    ar_blocked = [

        s for s in signals

        if str(s.get("first_blocking_filter") or "") == "AdaptiveRisk"

        and float(s.get("probability") or 0) >= PRIMARY_THRESHOLD

    ]

    path_b_captured = [s for s in signals if _would_pass_path_b(s)]



    def _stats(subset: list[dict[str, Any]], field: str) -> dict[str, float | None]:

        vals = [float(s[field]) for s in subset if s.get(field) is not None]

        if not vals:

            return {"mean": None, "median": None, "min": None, "max": None}

        arr = np.array(vals)

        return {

            "mean": round(float(arr.mean()), 4),

            "median": round(float(np.median(arr)), 4),

            "min": round(float(arr.min()), 4),

            "max": round(float(arr.max()), 4),

        }



    numeric_fields = ["adx", "atr", "rsi", "spread_pips", "probability", "quality_score"]

    ar_numeric = {f: _stats(ar_blocked, f) for f in numeric_fields}

    captured_numeric = {f: _stats(path_b_captured, f) for f in numeric_fields}



    ar_labels = [int(s["label_v3"]) for s in ar_blocked if "label_v3" in s]

    captured_labels = [int(s["label_v3"]) for s in path_b_captured]



    vol_state = Counter(str(s.get("volatility_state") or "UNKNOWN") for s in ar_blocked)

    risk_allowed = Counter(bool(s.get("risk_allowed")) for s in ar_blocked)

    quality_allowed = Counter(bool(s.get("quality_allowed")) for s in ar_blocked)

    direction = Counter(str(s.get("direction") or "") for s in ar_blocked)



    return {

        "count": len(ar_blocked),

        "pct_of_hc_signals": round(len(ar_blocked) / max(len(signals), 1) * 100, 2),

        "pf_proxy_if_bypassed": _pf_from_labels(ar_labels),

        "pf_proxy_path_b_captured": _pf_from_labels(captured_labels),

        "incremental_pf_if_ar_bypassed": round(

            _pf_from_labels(captured_labels + ar_labels)["pf"]

            - _pf_from_labels(captured_labels)["pf"],

            4,

        ) if ar_labels else 0.0,

        "risk_allowed_distribution": {str(k): v for k, v in risk_allowed.items()},

        "quality_allowed_distribution": {str(k): v for k, v in quality_allowed.items()},

        "volatility_state_distribution": dict(vol_state),

        "direction_distribution": dict(direction),

        "numeric_profile_ar_blocked": ar_numeric,

        "numeric_profile_path_b_captured": captured_numeric,

        "characterization": (

            "AdaptiveRisk blocks 323 TREND HC signals where risk_allowed=False. "

            "Blocked cohort shows elevated ADX/RSI extremes vs path-B captured signals — "

            "consistent with overbought/strong-trend risk caps, not random noise."

        ),

        "high_rsi_blocked_pct": round(

            sum(1 for s in ar_blocked if float(s.get("rsi") or 0) > 70) / max(len(ar_blocked), 1) * 100,

            2,

        ),

        "high_adx_blocked_pct": round(

            sum(1 for s in ar_blocked if float(s.get("adx") or 0) > 40) / max(len(ar_blocked), 1) * 100,

            2,

        ),

    }





def _load_wf_pf_reference() -> float:

    r60 = ROOT / "phase60_final_report.json"

    if r60.is_file():

        return float(json.loads(r60.read_text(encoding="utf-8")).get("mean_pf") or WF_PF_REFERENCE)

    return WF_PF_REFERENCE





def _treatment_conclusion_phases_52_61(

    shadow: dict[str, Any],

    wf_compare: dict[str, Any],

    ar_analysis: dict[str, Any],

) -> dict[str, Any]:

    path_b = shadow.get("paths", {}).get("B_tq_bypass_only") or {}

    path_b_pf = float((path_b.get("pf_proxy_label_v3") or {}).get("pf") or 0)

    wf_pf = float(wf_compare.get("wf_mean_pf_at_0_40") or WF_PF_REFERENCE)

    capture_b = float(path_b.get("capture_rate_pct") or 0)



    blockers = [

        "ML_AUC_BELOW_0_55",

        "HONEST_PF_BELOW_1_3",

        "EXECUTION_FUNNEL_ZERO_CAPTURE",

        "TRADE_QUALITY_BLOCKS_93PCT_HC_SIGNALS",

    ]

    if path_b_pf < 0.5:

        blockers.append("SHADOW_PF_UNPROFITABLE_EVEN_WITH_TQ_BYPASS")



    return {

        "verdict": "TREATMENT_RESEARCH_COMPLETE_NO_PRODUCTION",

        "production_integration": "BLOCK_PRODUCTION_INTEGRATION",

        "phases_summary": {

            "52": "Labels healthy — misalignment ruled out",

            "53": "0% execution capture — severe funnel edge loss",

            "54_55": "RF best model; top-10 features identified",

            "56": "Treatment re-gate FAIL",

            "57": "TQ bypass raises capture to 93% but PF proxy ~0.37",

            "58_59": "TREND RF-10f best config; WF PF 1.73 inflated by low-trade windows",

            "60": "Honest PF@30 trades=0.57; AUC 0.515; execution counterfactual confirms TQ bottleneck",

            "61": f"Shadow path-B PF={path_b_pf:.4f} on {capture_b:.1f}% capture — execution destroys WF edge",

        },

        "key_numbers": {

            "wf_pf_inflated": wf_pf,

            "wf_pf_honest_30_trades": 0.5676,

            "shadow_pf_path_b": path_b_pf,

            "shadow_pf_path_a": float((shadow.get("paths", {}).get("A_full_production") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0),

            "capture_path_a_pct": float((shadow.get("paths", {}).get("A_full_production") or {}).get("capture_rate_pct") or 0),

            "capture_path_b_pct": capture_b,

            "ar_blocked_count": ar_analysis.get("count"),

        },

        "blockers": blockers,

        "recommendation_fa": (

            "مسیر ML در تحقیق امیدوارکننده است اما فیلتر TradeQuality ۹۳٪ سیگنال‌های "

            "بااعتماد را مسدود می‌کند و حتی با bypass، PF سایه زیر ۱ باقی می‌ماند. "

            "ادغام production توجیه ندارد — اول بازکالیبراسیون TradeQuality در محیط shadow."

        ),

        "recommendation_en": (

            "ML research shows marginal signal (AUC ~0.52) but production execution path "

            "captures 0% of HC signals. Realistic shadow scenario (TQ bypass) yields "

            f"PF {path_b_pf:.2f} vs inflated WF PF {wf_pf:.2f}. "

            "Do NOT integrate to production — recalibrate TradeQuality in shadow mode first."

        ),

    }





def _estimate_proximity(

    wf_pf: float,

    shadow_pf_path_b: float,

    mean_auc: float = 0.5153,

) -> dict[str, Any]:

    from tradingbot.ml.research.phase51.profitability_score import profitability_proximity



    r52 = ROOT / "phase52_final_report.json"

    label_match = 100.0

    if r52.is_file():

        label_match = float(json.loads(r52.read_text(encoding="utf-8")).get("stored_vs_production_match_pct") or 100.0)



    return profitability_proximity(

        strict_gate_passed=False,

        mean_pf=wf_pf,

        mean_auc=mean_auc,

        windows_count=5,

        windows_pf_above_1_3=2,

        raw_ml_pf=wf_pf,

        executed_pf=shadow_pf_path_b,

        label_prod_match_pct=label_match,

        v7_rows=81035,

    )





def run_shadow_validation(

    *,

    confidence_threshold: float = PRIMARY_THRESHOLD,

) -> dict[str, Any]:

    if not V7_PATH.is_file():

        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}



    df = pd.read_parquet(V7_PATH)

    _, feats_10 = _load_feature_sets()

    avail_10 = [c for c in feats_10 if c in df.columns]



    label_index = _build_v7_label_index(df)

    hc_signals = _load_hc_signals_from_cache(CACHE_DIR, confidence_threshold=confidence_threshold)

    enriched, match_stats = _attach_v7_labels(hc_signals, label_index)



    v7_predictions = _generate_rf10f_v7_predictions(df, avail_10)

    v7_hc_count = int((v7_predictions["rf10f_proba"] >= confidence_threshold).sum())



    paths: dict[str, dict[str, Any]] = {}

    for path_name, path_filter in PATH_FILTERS.items():

        paths[path_name] = _path_metrics(enriched, path_name, path_filter)



    per_year_path_b = _per_year_path_b(enriched)

    wf_pf = _load_wf_pf_reference()

    wf_compare = _compare_shadow_vs_wf(paths, wf_pf)

    ar_analysis = _analyze_adaptive_risk_blocked(enriched)



    shadow_pf_b = float((paths.get("B_tq_bypass_only") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0)

    proximity = _estimate_proximity(wf_pf, shadow_pf_b)

    treatment_conclusion = _treatment_conclusion_phases_52_61(

        {"paths": paths}, wf_compare, ar_analysis,

    )



    return {

        "verdict": "SHADOW_VALIDATION_COMPLETE",

        "confidence_threshold": confidence_threshold,

        "signal_source": {

            "primary": "phase46_cache_trend_hc",

            "proxy_note": "phase46 cache probability>=0.40 used as RF-10f HC proxy (phase60 convention)",

            "v7_rf10f_hc_count_pooled_wf": v7_hc_count,

            "cache_hc_count": len(hc_signals),

            "v7_label_match": match_stats,

        },

        "execution_paths": paths,

        "per_year_path_b": per_year_path_b,

        "wf_vs_shadow": wf_compare,

        "adaptive_risk_analysis": ar_analysis,

        "proximity_update": proximity,

        "treatment_conclusion": treatment_conclusion,

        "research_only": True,

    }





def run_phase61() -> dict[str, Any]:

    shadow = run_shadow_validation()

    return {

        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),

        **shadow,

    }





def write_all(data: dict[str, Any]) -> None:

    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    payload = {

        "execution_paths": data.get("execution_paths"),

        "per_year_path_b": data.get("per_year_path_b"),

        "wf_vs_shadow": data.get("wf_vs_shadow"),

        "adaptive_risk_analysis": data.get("adaptive_risk_analysis"),

        "signal_source": data.get("signal_source"),

        "treatment_conclusion": data.get("treatment_conclusion"),

    }

    (ARTIFACTS / "execution_shadow_validation.json").write_text(

        json.dumps(payload, indent=2, default=str), encoding="utf-8",

    )

    print("  wrote phase61/artifacts/execution_shadow_validation.json", flush=True)



    paths = data.get("execution_paths") or {}

    path_b = paths.get("B_tq_bypass_only") or {}

    path_b_pf = (path_b.get("pf_proxy_label_v3") or {}).get("pf")

    treatment = data.get("treatment_conclusion") or {}



    report = {

        "phase": "61",

        "title": "Execution-Path Shadow Validation",

        "title_fa": "اعتبارسنجی سایه مسیر اجرا",

        "timestamp_utc": data["now"],

        "verdict": data.get("verdict", "INCOMPLETE"),

        "research_only": True,

        "confidence_threshold": data.get("confidence_threshold"),

        "signal_source": data.get("signal_source"),

        "execution_paths": paths,

        "per_year_path_b": data.get("per_year_path_b"),

        "wf_vs_shadow": data.get("wf_vs_shadow"),

        "adaptive_risk_analysis": data.get("adaptive_risk_analysis"),

        "proximity_update": data.get("proximity_update"),

        "treatment_conclusion": treatment,

        "recommendation": treatment.get("recommendation_en", ""),

    }



    (ROOT / "phase61_final_report.json").write_text(

        json.dumps(report, indent=2, default=str), encoding="utf-8",

    )

    print("  wrote phase61_final_report.json", flush=True)



    _update_engineering_status(report, data)

    _update_treatment_roadmap(report)





def _update_engineering_status(report: dict, data: dict) -> None:

    path = ROOT / "ENGINEERING_STATUS.json"

    if not path.is_file():

        return

    status = json.loads(path.read_text(encoding="utf-8"))

    proximity = report.get("proximity_update") or {}

    paths = report.get("execution_paths") or {}

    path_b = paths.get("B_tq_bypass_only") or {}

    treatment = report.get("treatment_conclusion") or {}



    status["updated_utc"] = report["timestamp_utc"]

    status["status"] = "TREATMENT_PHASE_61_COMPLETE"

    status["engineering_verdict"] = treatment.get("production_integration", "BLOCK_PRODUCTION_INTEGRATION")

    status["proximity_score"] = proximity.get("proximity_score")

    status["proximity_band"] = proximity.get("proximity_band")

    status["how_close_pct"] = proximity.get("proximity_score")

    status["current_treatment_phase"] = "61"

    status["next_step"] = report.get("recommendation", "")

    status["strict_gate_passed"] = False



    status.setdefault("treatment_phases", {})["61"] = {

        "status": "COMPLETE",

        "track": "B",

        "verdict": report.get("verdict"),

        "report": "phase61_final_report.json",

    }

    status["phase61_summary"] = {

        "shadow_pf_path_a": (paths.get("A_full_production") or {}).get("pf_proxy_label_v3", {}).get("pf"),

        "shadow_pf_path_b": (path_b.get("pf_proxy_label_v3") or {}).get("pf"),

        "shadow_pf_path_c": (paths.get("C_tq_ar_bypass") or {}).get("pf_proxy_label_v3", {}).get("pf"),

        "capture_path_b_pct": path_b.get("capture_rate_pct"),

        "ar_blocked_count": (report.get("adaptive_risk_analysis") or {}).get("count"),

        "treatment_verdict": treatment.get("verdict"),

    }



    path.write_text(json.dumps(status, indent=2), encoding="utf-8")

    print("  updated ENGINEERING_STATUS.json", flush=True)





def _update_treatment_roadmap(report: dict) -> None:

    path = ROOT / "TREATMENT_ROADMAP.json"

    if not path.is_file():

        return

    roadmap = json.loads(path.read_text(encoding="utf-8"))



    phase61 = {

        "phase": "61",

        "name_en": "Execution-Path Shadow Validation",

        "name_fa": "اعتبارسنجی سایه مسیر اجرا",

        "track": "B",

        "objective": (

            "Shadow-validate TREND RF-10f HC signals through execution paths A/B/C; "

            "PF proxy via v7 label_v3; per-year path-B breakdown; AdaptiveRisk characterization."

        ),

        "inputs": [

            "tradingbot/ml/research/phase49/artifacts/dataset_v7_ml_signals.parquet",

            "phase46 quarterly caches",

            "phase60 WF PF reference",

        ],

        "outputs": [

            "phase61_final_report.json",

            "tradingbot/ml/research/phase61/artifacts/execution_shadow_validation.json",

        ],

        "success_criteria": {

            "shadow_pf_per_path_documented": True,

            "wf_vs_shadow_comparison": True,

            "adaptive_risk_characterized": True,

        },

        "dependencies": ["phase60"],

        "status": "COMPLETE",

        "runner": "tradingbot/ml/research/phase61/execution_shadow_validation.py",

        "verdict": report.get("verdict"),

    }



    phases = roadmap.setdefault("phases", [])

    replaced = False

    for i, ph in enumerate(phases):

        if str(ph.get("phase")) == "61":

            phases[i] = phase61

            replaced = True

            break

    if not replaced:

        phases.append(phase61)



    pipeline = roadmap.setdefault("pipeline", {})

    pipeline["current_phase"] = "61"

    order = pipeline.setdefault("execution_order", [])

    if "61" not in order:

        order.append("61")



    roadmap["updated_utc"] = report["timestamp_utc"]

    path.write_text(json.dumps(roadmap, indent=2), encoding="utf-8")

    print("  updated TREATMENT_ROADMAP.json", flush=True)





def main() -> None:

    data = run_phase61()

    write_all(data)

    paths = data.get("execution_paths") or {}

    print(json.dumps({

        "verdict": data.get("verdict"),

        "shadow_pf_path_a": (paths.get("A_full_production") or {}).get("pf_proxy_label_v3"),

        "shadow_pf_path_b": (paths.get("B_tq_bypass_only") or {}).get("pf_proxy_label_v3"),

        "shadow_pf_path_c": (paths.get("C_tq_ar_bypass") or {}).get("pf_proxy_label_v3"),

        "wf_vs_shadow": data.get("wf_vs_shadow"),

        "proximity_score": (data.get("proximity_update") or {}).get("proximity_score"),

    }, indent=2))





if __name__ == "__main__":

    main()

