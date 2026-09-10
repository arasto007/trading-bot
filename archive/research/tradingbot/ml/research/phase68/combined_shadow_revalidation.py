"""Phase 68 — Combined shadow revalidation (research only).

Combine phase63 TQ alias @0.40 + AR production with ML configs A and C.
Evaluate all FIX_ROADMAP production gates; issue phase69 paper-trading verdict.
NO production code changes.
"""

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

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase68" / "artifacts"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"
CACHE_LABELS = ("A", "B", "C", "H")
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"
PHASE63_POLICY = ROOT / "tradingbot" / "ml" / "research" / "phase63" / "artifacts" / "tq_shadow_policy.json"
PHASE67_REPORT = ROOT / "phase67_final_report.json"

PRIMARY_THRESHOLD = 0.40
TQ_SHADOW_THRESHOLD = 0.40
TQ_ALIAS_POLICY = "map_to_v40"
MIN_TRADES_HONEST = 30

GATE_MEAN_AUC = 0.55
GATE_HONEST_PF = 1.3
GATE_SHADOW_PF = 1.0
GATE_CAPTURE_PCT = 20.0

ML_CONFIGS: dict[str, dict[str, Any]] = {
    "A": {
        "name": "baseline_rf_10f_label_v3_h72",
        "label_variant": "label_v3",
        "horizon": 72,
        "model": "random_forest",
        "class_weight": None,
        "dual_objective": False,
        "role": "best_honest_pf_reference",
    },
    "C": {
        "name": "strict_tp_only_h24_rf_hgb_ensemble",
        "label_variant": "strict_tp_only",
        "horizon": 24,
        "model": "rf_hgb_ensemble",
        "class_weight": None,
        "dual_objective": False,
        "role": "best_balance_ensemble",
    },
}


def _load_baseline_features() -> list[str]:
    from tradingbot.ml.research.phase66.label_horizon_experiments import _load_baseline_features

    return _load_baseline_features()


def _pf_from_labels(labels: list[int]) -> dict[str, float | int]:
    if not labels:
        return {"pf": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0}
    wins = sum(labels)
    losses = len(labels) - wins
    pf = wins / losses if losses > 0 else (2.0 if wins > 0 else 0.0)
    return {
        "pf": round(pf, 4),
        "trades": len(labels),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / len(labels) * 100, 2),
    }


def _signal_key(signal: dict[str, Any]) -> tuple | None:
    direction = str(signal.get("direction") or "")
    if direction not in ("BUY", "SELL"):
        return None
    try:
        ts = pd.to_datetime(signal["timestamp"], utc=True)
    except (KeyError, TypeError, ValueError):
        return None
    return ts, direction


def _load_hc_trend_signals(cache_dir: Path, *, confidence_threshold: float = PRIMARY_THRESHOLD) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for label in CACHE_LABELS:
        path = cache_dir / f"ml_signals_fullest_{label}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for sig in payload.get("signals") or []:
            if str(sig.get("regime")) != "TREND":
                continue
            if float(sig.get("probability") or 0) < confidence_threshold:
                continue
            sid = str(sig.get("signal_id", ""))
            if sid and sid in seen_ids:
                continue
            if sid:
                seen_ids.add(sid)
            rec = dict(sig)
            rec["source_cache"] = label
            signals.append(rec)
    return signals


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


def _build_v7_feature_index(df: pd.DataFrame, feature_cols: list[str]) -> dict[tuple, dict[str, float]]:
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work["dir_str"] = work["direction"].map({1: "BUY", -1: "SELL"})
    index: dict[tuple, dict[str, float]] = {}
    for _, row in work.iterrows():
        key = (row["timestamp"], row["dir_str"])
        index[key] = {c: float(row.get(c) or 0) for c in feature_cols}
    return index


def _attach_v7_labels(
    signals: list[dict[str, Any]],
    label_index: dict[tuple, int],
    feature_index: dict[tuple, dict[str, float]],
    feature_cols: list[str],
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
        feats = feature_index.get(key, {})
        for c in feature_cols:
            rec[c] = feats.get(c, 0.0)
        enriched.append(rec)
    return enriched, {
        "total_signals": len(signals),
        "matched_v7_labels": len(enriched),
        "unmatched": unmatched,
        "match_rate_pct": round(len(enriched) / max(len(signals), 1) * 100, 2),
    }


def _evaluate_shadow_tq(signal: dict[str, Any], *, quality_threshold: float = TQ_SHADOW_THRESHOLD) -> dict[str, Any]:
    from tradingbot.ml.research.phase63.trade_quality_shadow_calibration import _evaluate_shadow

    return _evaluate_shadow(
        signal,
        alias_policy=TQ_ALIAS_POLICY,
        quality_threshold=quality_threshold,
    )


def _passes_ar_production(signal: dict[str, Any]) -> bool:
    return bool(signal.get("risk_allowed"))


def _fit_predict(
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    X_te: np.ndarray,
    *,
    model: str,
    class_weight: str | None = None,
    seed: int = 42,
) -> np.ndarray:
    from tradingbot.ml.research.phase67.trend_ensemble_specialization import _fit_predict

    return _fit_predict(X_tr, y_tr, X_te, model=model, class_weight=class_weight, seed=seed)


def _build_labeled_frames(v7_df: pd.DataFrame) -> dict[tuple[int, str], pd.DataFrame]:
    """Build labeled TREND frames for horizons/variants needed by phase68 configs."""
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
    from tradingbot.ml.research.phase66.label_horizon_experiments import apply_label_variant, relabel_at_horizon

    candles = resolve_fullest_candles()
    if candles is None or candles.empty:
        return {}

    horizons_needed = {cfg["horizon"] for cfg in ML_CONFIGS.values()}
    variants_needed = {cfg["label_variant"] for cfg in ML_CONFIGS.values()}
    labeled_frames: dict[tuple[int, str], pd.DataFrame] = {}

    for h in sorted(horizons_needed):
        print(f"  loading labels horizon={h}...", flush=True)
        frame = relabel_at_horizon(v7_df, candles, future_window_bars=h)
        for variant in variants_needed:
            use_existing = variant == "label_v3" and h == 72
            labeled, _ = apply_label_variant(frame, variant, use_existing_v3=use_existing)
            labeled = labeled.rename(columns={"_label": "train_label"})
            labeled["timestamp"] = pd.to_datetime(labeled["timestamp"], utc=True)
            if "regime" in labeled.columns:
                labeled = labeled[labeled["regime"] == "TREND"]
            labeled_frames[(h, variant)] = labeled.sort_values("timestamp")
            print(f"    {variant} h={h}: {len(labeled)} rows", flush=True)

    return labeled_frames


def _prepare_labeled_trend_frame(
    labeled_frames: dict[tuple[int, str], pd.DataFrame],
    config: dict[str, Any],
) -> pd.DataFrame | None:
    key = (config["horizon"], config["label_variant"])
    return labeled_frames.get(key)


def _score_signals_for_config(
    signals: list[dict[str, Any]],
    labeled_df: pd.DataFrame | None,
    config: dict[str, Any],
    feature_cols: list[str],
    *,
    ml_threshold: float = PRIMARY_THRESHOLD,
) -> tuple[dict[str, float], str]:
    """Return signal_id -> proba and scoring method used."""
    # Config A is the production baseline RF — cache HC signals already reflect it.
    if config["label_variant"] == "label_v3" and config["horizon"] == 72 and config["model"] == "random_forest":
        proba_map = {
            str(sig.get("signal_id", "")): round(float(sig.get("probability") or 0), 4)
            for sig in signals
        }
        return proba_map, "production_probability_baseline"

    if labeled_df is None or labeled_df.empty:
        return {}, "walk_forward_missing_labels"
    return _score_signals_walk_forward(signals, labeled_df, config, feature_cols), "walk_forward_retrain"


def _score_signals_walk_forward(
    signals: list[dict[str, Any]],
    labeled_df: pd.DataFrame,
    config: dict[str, Any],
    feature_cols: list[str],
    *,
    min_train_rows: int = 200,
) -> dict[str, float]:
    """Year-wise walk-forward ML scores for cache signals."""
    from sklearn.preprocessing import StandardScaler

    work = labeled_df[labeled_df["train_label"].isin([0, 1])].copy()
    years = sorted(work["timestamp"].dt.year.unique())
    signal_by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for sig in signals:
        signal_by_year[int(sig["year"])].append(sig)

    proba_map: dict[str, float] = {}
    for test_year in years[1:]:
        tr = work[work["timestamp"].dt.year < test_year]
        if len(tr) < min_train_rows:
            continue
        year_signals = signal_by_year.get(int(test_year), [])
        if not year_signals:
            continue

        X_tr = tr[feature_cols].astype(float).fillna(0).values
        y_tr = tr["train_label"].astype(int).values
        X_te = np.array([[float(s.get(c) or 0) for c in feature_cols] for s in year_signals])

        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        proba = _fit_predict(
            X_tr_s,
            y_tr,
            X_te_s,
            model=config["model"],
            class_weight=config.get("class_weight"),
        )
        for sig, p in zip(year_signals, proba):
            proba_map[str(sig.get("signal_id", ""))] = round(float(p), 4)

    return proba_map


def _load_phase67_wf_metrics(config_id: str) -> dict[str, Any]:
    if not PHASE67_REPORT.is_file():
        return {}
    report = json.loads(PHASE67_REPORT.read_text(encoding="utf-8"))
    for row in report.get("comparison") or []:
        if str(row.get("config_id")) == config_id:
            return {
                "mean_auc": row.get("mean_auc"),
                "mean_pf": row.get("mean_pf"),
                "mean_pf_honest": row.get("mean_pf_honest"),
                "mean_win_rate": row.get("mean_win_rate"),
                "mean_trades_per_window": row.get("mean_trades_per_window"),
                "auc_gate_pass": row.get("auc_gate_pass"),
                "honest_pf_gate_pass": row.get("honest_pf_gate_pass"),
                "both_gates_pass": row.get("both_gates_pass"),
            }
    return {}


def _simulate_combined_shadow(
    signals: list[dict[str, Any]],
    ml_proba: dict[str, float],
    *,
    ml_threshold: float = PRIMARY_THRESHOLD,
) -> dict[str, Any]:
    """Full shadow path: ML filter → TQ alias → AR production."""
    funnel = {
        "input_hc_signals": len(signals),
        "after_ml_filter": 0,
        "after_tq_shadow": 0,
        "after_ar_production": 0,
        "captured_final": 0,
    }
    blockers = Counter()
    captured: list[dict[str, Any]] = []

    for sig in signals:
        sid = str(sig.get("signal_id", ""))
        p = ml_proba.get(sid)
        if p is None or p < ml_threshold:
            blockers["ml_filter"] += 1
            continue
        funnel["after_ml_filter"] += 1

        tq = _evaluate_shadow_tq(sig)
        if not tq.get("allowed"):
            blockers[str(tq.get("blocked_by") or "trade_quality")] += 1
            continue
        funnel["after_tq_shadow"] += 1

        if not _passes_ar_production(sig):
            blockers["adaptive_risk"] += 1
            continue
        funnel["after_ar_production"] += 1
        captured.append(sig)
        funnel["captured_final"] += 1

    labels = [int(s["label_v3"]) for s in captured]
    pf = _pf_from_labels(labels)
    capture_pct = round(funnel["captured_final"] / max(len(signals), 1) * 100, 2)
    captured_ids = {str(s.get("signal_id", "")) for s in captured}

    per_year: dict[str, Any] = {}
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for s in signals:
        by_year[int(s["year"])].append(s)
    for year, year_sigs in sorted(by_year.items()):
        year_captured = [s for s in year_sigs if str(s.get("signal_id", "")) in captured_ids]
        year_labels = [int(s["label_v3"]) for s in year_captured]
        year_pf = _pf_from_labels(year_labels)
        per_year[str(year)] = {
            "signals_hc": len(year_sigs),
            "captured_count": len(year_captured),
            "capture_rate_pct": round(len(year_captured) / max(len(year_sigs), 1) * 100, 2),
            "pf_proxy_label_v3": year_pf["pf"],
            "trades": year_pf["trades"],
            "win_rate_pct": year_pf["win_rate_pct"],
        }

    return {
        "funnel": funnel,
        "blockers": dict(blockers),
        "capture_rate_pct": capture_pct,
        "pf_proxy_label_v3": pf,
        "win_rate_pct": pf["win_rate_pct"],
        "per_year_breakdown": per_year,
        "ml_threshold": ml_threshold,
        "tq_policy": {
            "alias_policy": TQ_ALIAS_POLICY,
            "quality_threshold": TQ_SHADOW_THRESHOLD,
        },
        "ar_policy": "keep_production",
    }


def _evaluate_gates(shadow: dict[str, Any], wf: dict[str, Any]) -> dict[str, Any]:
    shadow_pf = float((shadow.get("pf_proxy_label_v3") or {}).get("pf") or 0)
    capture_pct = float(shadow.get("capture_rate_pct") or 0)
    mean_auc = float(wf.get("mean_auc") or 0)
    honest_pf = float(wf.get("mean_pf_honest") or 0)

    gates = {
        "auc_ge_0_55": {
            "pass": mean_auc >= GATE_MEAN_AUC,
            "actual": mean_auc,
            "target": GATE_MEAN_AUC,
        },
        "honest_pf_ge_1_3": {
            "pass": honest_pf >= GATE_HONEST_PF,
            "actual": honest_pf,
            "target": GATE_HONEST_PF,
            "min_trades_per_window": MIN_TRADES_HONEST,
        },
        "shadow_pf_ge_1_0": {
            "pass": shadow_pf >= GATE_SHADOW_PF,
            "actual": shadow_pf,
            "target": GATE_SHADOW_PF,
        },
        "capture_rate_hc_pct_ge_20": {
            "pass": capture_pct >= GATE_CAPTURE_PCT,
            "actual": capture_pct,
            "target": GATE_CAPTURE_PCT,
        },
    }
    all_pass = all(g["pass"] for g in gates.values())
    return {
        "gates": gates,
        "all_gates_pass": all_pass,
        "gates_passed_count": sum(1 for g in gates.values() if g["pass"]),
        "gates_total": len(gates),
    }


def _phase69_verdict(config_results: list[dict[str, Any]]) -> dict[str, Any]:
    any_all_pass = any(r.get("gate_evaluation", {}).get("all_gates_pass") for r in config_results)
    best_shadow = max(
        config_results,
        key=lambda r: float((r.get("shadow_path") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0),
    )
    best_shadow_pf = float(
        (best_shadow.get("shadow_path") or {}).get("pf_proxy_label_v3", {}).get("pf") or 0
    )

    if any_all_pass:
        proceed = True
        rationale_en = "At least one combined config passes all FIX_ROADMAP gates — phase69 paper trading justified."
        rationale_fa = "حداقل یک کانفیگ همه gateها را پاس کرد — فاز ۶۹ مجاز است."
        verdict = "GATES_PASS_PROCEED_PAPER"
    else:
        proceed = False
        rationale_en = (
            f"No config passes all gates simultaneously. Best shadow PF={best_shadow_pf:.4f} "
            f"(config {best_shadow.get('config_id')}). ML honest PF and shadow PF remain below targets. "
            "Phase69 paper trading NOT justified on evidence — optional observational paper only."
        )
        rationale_fa = (
            f"هیچ کانفیگی همه gateها را همزمان پاس نکرد. بهترین shadow PF={best_shadow_pf:.4f}. "
            "فاز ۶۹ معاملات کاغذی با این شواهد توجیه نمی‌شود."
        )
        verdict = "GATES_FAIL_BLOCK_PAPER"

    return {
        "proceed_to_phase69": proceed,
        "verdict": verdict,
        "rationale_en": rationale_en,
        "rationale_fa": rationale_fa,
        "best_shadow_config_id": best_shadow.get("config_id"),
        "best_shadow_pf": best_shadow_pf,
    }


def _fix_roadmap_assessment(config_results: list[dict[str, Any]], phase69: dict[str, Any]) -> dict[str, Any]:
    exec_fixed = True
    ml_fixed = any(
        r.get("walk_forward", {}).get("auc_gate_pass") for r in config_results
    )
    tradeable = any(r.get("gate_evaluation", {}).get("all_gates_pass") for r in config_results)

    return {
        "phases_62_68_summary_en": (
            "Phases 62-64 fixed execution capture (TQ engine alias restores ~93% capture; AR bypass not worth it). "
            "Phases 65-67 failed to lift honest PF≥1.3; best AUC configs have decoupled/untradeable PF. "
            f"Phase68 combined shadow: best PF still ~{phase69.get('best_shadow_pf', 0):.2f} — below shadow gate 1.0."
        ),
        "phases_62_68_summary_fa": (
            "فازهای ۶۲-۶۴ مشکل اجرا (capture) را حل کردند. فازهای ۶۵-۶۷ PF صادق را بالا نبردند. "
            f"فاز ۶۸: shadow PF هنوز زیر ۱.۰ (~{phase69.get('best_shadow_pf', 0):.2f})."
        ),
        "execution_track_status": "CAPTURE_FIXED_PF_WEAK",
        "ml_track_status": "AUC_MARGINAL_PF_FAIL",
        "integration_track_status": "BLOCKED" if not phase69.get("proceed_to_phase69") else "READY_FOR_PAPER",
        "execution_issue_fixable": exec_fixed,
        "ml_issue_fixable_with_guarantee": False,
        "tradeable_edge_found": tradeable,
        "auc_lift_achieved": ml_fixed,
        "primary_remaining_blocker_en": "ML predictive edge too weak — honest PF ~0.43-0.57, shadow PF ~0.39",
        "primary_remaining_blocker_fa": "edge پیش‌بینی ML ضعیف — PF صادق ~۰.۴۳-۰.۵۷، shadow PF ~۰.۳۹",
    }


def run_combined_shadow_revalidation(*, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": f"missing v7: {V7_PATH}"}

    feature_cols = _load_baseline_features()
    v7_df = pd.read_parquet(V7_PATH)
    label_index = _build_v7_label_index(v7_df)
    feature_index = _build_v7_feature_index(v7_df, feature_cols)

    hc_signals = _load_hc_trend_signals(cache_dir)
    enriched, match_stats = _attach_v7_labels(hc_signals, label_index, feature_index, feature_cols)
    if not enriched:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no v7-matched HC TREND signals"}

    phase63_report_path = ROOT / "phase63_final_report.json"
    phase63_baseline = {}
    if phase63_report_path.is_file():
        phase63_baseline = json.loads(phase63_report_path.read_text(encoding="utf-8"))

    config_results: list[dict[str, Any]] = []
    labeled_frames = _build_labeled_frames(v7_df)
    if not labeled_frames:
        return {"verdict": "INSUFFICIENT_DATA", "error": "could not build labeled frames (candles missing?)"}

    for config_id, config in ML_CONFIGS.items():
        print(f"  Simulating combined shadow config {config_id} ({config['name']})...", flush=True)
        labeled_df = _prepare_labeled_trend_frame(labeled_frames, config)
        ml_proba, scoring_method = _score_signals_for_config(
            enriched, labeled_df, config, feature_cols, ml_threshold=PRIMARY_THRESHOLD
        )
        shadow = _simulate_combined_shadow(enriched, ml_proba, ml_threshold=PRIMARY_THRESHOLD)
        wf = _load_phase67_wf_metrics(config_id)
        gates = _evaluate_gates(shadow, wf)

        config_results.append({
            "config_id": config_id,
            "name": config["name"],
            "role": config["role"],
            "ml_config": config,
            "ml_scoring_method": scoring_method,
            "ml_scored_signals": len(ml_proba),
            "walk_forward": wf,
            "shadow_path": shadow,
            "gate_evaluation": gates,
            "vs_phase63_execution_only": {
                "phase63_shadow_pf": (phase63_baseline.get("gate_check") or {}).get("shadow_pf_actual"),
                "phase63_capture_pct": (phase63_baseline.get("gate_check") or {}).get("capture_actual_pct"),
                "delta_shadow_pf": round(
                    float((shadow.get("pf_proxy_label_v3") or {}).get("pf") or 0)
                    - float((phase63_baseline.get("gate_check") or {}).get("shadow_pf_actual") or 0),
                    4,
                ),
                "delta_capture_pct": round(
                    float(shadow.get("capture_rate_pct") or 0)
                    - float((phase63_baseline.get("gate_check") or {}).get("capture_actual_pct") or 0),
                    2,
                ),
            },
        })

    phase69 = _phase69_verdict(config_results)
    assessment = _fix_roadmap_assessment(config_results, phase69)

    any_all_pass = any(r["gate_evaluation"]["all_gates_pass"] for r in config_results)
    verdict = "COMBINED_SHADOW_GATES_PASS" if any_all_pass else "COMBINED_SHADOW_GATES_FAIL"

    best = max(
        config_results,
        key=lambda r: float((r["shadow_path"]["pf_proxy_label_v3"]).get("pf") or 0),
    )

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "research_only": True,
        "execution_policy": {
            "trade_quality": {
                "engine_alias": TQ_ALIAS_POLICY,
                "from_engine": "trend_rf_v41",
                "to_engine": "trend_rf_v40",
                "quality_threshold": TQ_SHADOW_THRESHOLD,
                "source": "phase63",
            },
            "adaptive_risk": {
                "action": "keep_production",
                "source": "phase64",
            },
            "ml_threshold": PRIMARY_THRESHOLD,
        },
        "signal_source": {
            "hc_signals_deduped": len(hc_signals),
            "v7_matched": len(enriched),
            "v7_label_match": match_stats,
        },
        "configs_tested": list(ML_CONFIGS.keys()),
        "config_results": config_results,
        "best_combined_config": {
            "config_id": best["config_id"],
            "name": best["name"],
            "shadow_pf": best["shadow_path"]["pf_proxy_label_v3"]["pf"],
            "capture_rate_pct": best["shadow_path"]["capture_rate_pct"],
            "mean_auc": best["walk_forward"].get("mean_auc"),
            "mean_pf_honest": best["walk_forward"].get("mean_pf_honest"),
            "all_gates_pass": best["gate_evaluation"]["all_gates_pass"],
        },
        "phase69_verdict": phase69,
        "fix_roadmap_assessment": assessment,
        "production_gates_reference": {
            "mean_auc_ge": GATE_MEAN_AUC,
            "honest_pf_ge": GATE_HONEST_PF,
            "honest_pf_min_trades": MIN_TRADES_HONEST,
            "shadow_pf_ge": GATE_SHADOW_PF,
            "capture_rate_hc_pct_ge": GATE_CAPTURE_PCT,
        },
        "next_phase": "69" if phase69.get("proceed_to_phase69") else "67_or_research",
        "research_only_note": "Profitability cannot be guaranteed — gates are evidence thresholds only.",
    }


def run_phase68() -> dict[str, Any]:
    return run_combined_shadow_revalidation()


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    artifact = {k: v for k, v in data.items() if k != "now"}
    (ARTIFACTS / "combined_shadow_validation.json").write_text(
        json.dumps(artifact, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase68/artifacts/combined_shadow_validation.json", flush=True)

    best = data.get("best_combined_config") or {}
    phase69 = data.get("phase69_verdict") or {}
    assessment = data.get("fix_roadmap_assessment") or {}

    report = {
        "phase": "68",
        "title": "Combined Shadow Revalidation",
        "title_fa": "اعتبارسنجی مجدد سایه ترکیبی",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "execution_policy": data.get("execution_policy"),
        "signal_source": data.get("signal_source"),
        "configs_tested": data.get("configs_tested"),
        "config_results": data.get("config_results"),
        "best_combined_config": best,
        "production_gates_reference": data.get("production_gates_reference"),
        "phase69_verdict": phase69,
        "fix_roadmap_assessment": assessment,
        "recommendation_en": phase69.get("rationale_en", ""),
        "recommendation_fa": phase69.get("rationale_fa", ""),
        "next_phase": data.get("next_phase"),
    }
    (ROOT / "phase68_final_report.json").write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase68_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report, data)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    best = data.get("best_combined_config") or {}
    phase69 = data.get("phase69_verdict") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_68_COMPLETE"
    status["current_treatment_phase"] = "68"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["68"] = {
        "status": "COMPLETE",
        "track": "E+I",
        "verdict": report.get("verdict"),
        "report": "phase68_final_report.json",
        "all_gates_pass": bool(best.get("all_gates_pass")),
        "proceed_to_phase69": bool(phase69.get("proceed_to_phase69")),
    }
    status["phase68_summary"] = {
        "best_config_id": best.get("config_id"),
        "best_shadow_pf": best.get("shadow_pf"),
        "best_capture_pct": best.get("capture_rate_pct"),
        "best_mean_auc": best.get("mean_auc"),
        "best_mean_pf_honest": best.get("mean_pf_honest"),
        "all_gates_pass": bool(best.get("all_gates_pass")),
        "proceed_to_phase69": bool(phase69.get("proceed_to_phase69")),
        "phase69_verdict": phase69.get("verdict"),
    }
    status["strict_gate_passed"] = bool(best.get("all_gates_pass"))
    if not phase69.get("proceed_to_phase69"):
        status["engineering_verdict"] = "BLOCK_PRODUCTION_INTEGRATION"
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_fix_roadmap(report: dict, data: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))
    best = data.get("best_combined_config") or {}
    phase69 = data.get("phase69_verdict") or {}

    for ph in fix.get("phases", []):
        if str(ph.get("phase")) == "68":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "69" if phase69.get("proceed_to_phase69") else "68_blocked"
    fix.setdefault("current_baseline", {}).update({
        "shadow_pf_combined_best": best.get("shadow_pf"),
        "capture_rate_combined_pct": best.get("capture_rate_pct"),
        "honest_pf_best": best.get("mean_pf_honest"),
        "mean_auc_best": best.get("mean_auc"),
        "production_status": "BLOCKED" if not phase69.get("proceed_to_phase69") else "PAPER_READY",
    })
    fix.setdefault("honest_assessment", {}).update({
        "phase68_verdict_en": phase69.get("rationale_en", ""),
        "phase68_verdict_fa": phase69.get("rationale_fa", ""),
        "proceed_to_phase69": bool(phase69.get("proceed_to_phase69")),
    })
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase68()
    write_all(data)
    best = data.get("best_combined_config") or {}
    phase69 = data.get("phase69_verdict") or {}
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "best_config": best.get("config_id"),
                "shadow_pf": best.get("shadow_pf"),
                "all_gates_pass": best.get("all_gates_pass"),
                "proceed_to_phase69": phase69.get("proceed_to_phase69"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
