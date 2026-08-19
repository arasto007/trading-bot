"""Phase 66 — Label & horizon experiments on TREND subset (research only).

Sweep future_window_bars (24–120) with full walk-forward retrain and compare
label definitions: label_v3, strict_tp_only, tp_vs_sl_binary, rr_weighted.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase66" / "artifacts"
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"
LABEL_CACHE = ARTIFACTS / "relabel_cache"

PRIMARY_THRESHOLD = 0.40
GATE_MEAN_PF = 1.3
GATE_MEAN_AUC = 0.55
MIN_TRADES_FLOOR = 30
MIN_TRADES_DEFAULT = 15

HORIZONS = [24, 36, 48, 72, 96, 120]
LABEL_VARIANTS = ("label_v3", "strict_tp_only", "tp_vs_sl_binary", "rr_weighted")

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

BASELINE_AUC = 0.5153
BASELINE_PF = 1.7343
BASELINE_HONEST_PF = 0.5676


def _load_baseline_features() -> list[str]:
    r55 = ROOT / "phase55_final_report.json"
    if r55.is_file():
        feats = list(json.loads(r55.read_text(encoding="utf-8")).get("top_features") or [])
        if len(feats) >= 10:
            return feats[:10]
    return list(BASELINE_10F)


def _load_trend_df(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "regime" in work.columns:
        work = work[work["regime"] == "TREND"]
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    return work.sort_values("timestamp").reset_index(drop=True)


def _compute_rr(entry: float, sl: float, tp: float) -> float:
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    if sl_dist <= 0:
        return 1.0
    return round(float(tp_dist / sl_dist), 4)


def relabel_at_horizon(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    future_window_bars: int,
    sample_frac: float | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Re-resolve TP/SL labels at a given horizon using fullest candles."""
    from tradingbot.ml.dataset.schema import Label
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
    from tradingbot.ml.research.phase49.bar_index import resolve_bar_index

    cache_path = LABEL_CACHE / f"horizon_{future_window_bars}.parquet"
    if cache_path.is_file():
        cached = pd.read_parquet(cache_path)
        if sample_frac is None or "sample_frac" not in cached.columns or (
            cached["sample_frac"].iloc[0] == sample_frac
        ):
            return cached

    work = _load_trend_df(df)
    if sample_frac is not None and 0 < sample_frac < 1.0:
        work = (
            work.groupby(work["timestamp"].dt.year, group_keys=False)
            .apply(lambda g: g.sample(frac=sample_frac, random_state=seed))
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

    highs = candles["high"].astype(float).to_numpy()
    lows = candles["low"].astype(float).to_numpy()
    n_candles = len(candles)

    resolved_labels: list[int | None] = []
    tp_hits: list[bool] = []
    sl_hits: list[bool] = []
    rr_ratios: list[float] = []
    exit_bars: list[int | None] = []

    t0 = time.time()
    for i, row in work.iterrows():
        idx = int(row["bar_index"]) if pd.notna(row.get("bar_index")) else resolve_bar_index(
            candles, row["timestamp"],
        )
        if idx < 20 or idx >= n_candles - future_window_bars - 1:
            resolved_labels.append(None)
            tp_hits.append(False)
            sl_hits.append(False)
            rr_ratios.append(1.0)
            exit_bars.append(None)
            continue

        direction = int(row["direction"])
        entry = float(row["entry_price"])
        sl = float(row.get("stop_loss_v3", row.get("stop_loss", 0)))
        tp = float(row.get("take_profit_v3", row.get("take_profit", 0)))
        if sl <= 0 or tp <= 0:
            resolved_labels.append(None)
            tp_hits.append(False)
            sl_hits.append(False)
            rr_ratios.append(1.0)
            exit_bars.append(None)
            continue

        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl, tp,
            future_window_bars=future_window_bars,
            entry_price=entry,
        )
        label = int(resolved["label"])
        resolved_labels.append(label)
        tp_hits.append(bool(resolved.get("tp_hit")))
        sl_hits.append(bool(resolved.get("sl_hit")))
        rr_ratios.append(_compute_rr(entry, sl, tp))
        exit_bars.append(int(resolved["bars"]) if resolved.get("bars") is not None else None)

        if (i + 1) % 10000 == 0:
            elapsed = time.time() - t0
            print(f"    relabel h={future_window_bars}: {i + 1}/{len(work)} ({elapsed:.1f}s)", flush=True)

    out = work.copy()
    out["resolved_label"] = resolved_labels
    out["tp_hit"] = tp_hits
    out["sl_hit"] = sl_hits
    out["rr_ratio"] = rr_ratios
    out["exit_bars"] = exit_bars
    out["future_window_bars"] = future_window_bars
    if sample_frac is not None:
        out["sample_frac"] = sample_frac

    LABEL_CACHE.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache_path, index=False)
    print(f"    cached horizon {future_window_bars} ({len(out)} rows, {time.time() - t0:.1f}s)", flush=True)
    return out


def apply_label_variant(
    df: pd.DataFrame,
    variant: str,
    *,
    use_existing_v3: bool = False,
) -> tuple[pd.DataFrame, str | None]:
    """Build binary label column and optional sample-weight column for a variant."""
    from tradingbot.ml.dataset.schema import Label

    work = df.copy()
    weight_col: str | None = None

    if variant == "label_v3":
        if use_existing_v3 and "label_v3" in work.columns and "resolved_label" not in work.columns:
            work["_label"] = work["label_v3"]
        else:
            rl = work["resolved_label"]
            work["_label"] = np.where(
                rl == int(Label.TP_FIRST), 1,
                np.where(rl == int(Label.SL_FIRST), 0, np.nan),
            )
        work = work[work["_label"].isin([0, 1])]
        return work, weight_col

    if variant == "strict_tp_only":
        rl = work["resolved_label"]
        work = work[rl.notna()].copy()
        work["_label"] = (work["resolved_label"] == int(Label.TP_FIRST)).astype(int)
        return work, weight_col

    if variant == "tp_vs_sl_binary":
        rl = work["resolved_label"]
        mask = rl.isin([int(Label.TP_FIRST), int(Label.SL_FIRST)])
        work = work[mask].copy()
        work["_label"] = (work["resolved_label"] == int(Label.TP_FIRST)).astype(int)
        return work, weight_col

    if variant == "rr_weighted":
        rl = work["resolved_label"]
        work["_label"] = np.where(
            rl == int(Label.TP_FIRST), 1,
            np.where(rl == int(Label.SL_FIRST), 0, np.nan),
        )
        work = work[work["_label"].isin([0, 1])].copy()
        work["_sample_weight"] = work["rr_ratio"].clip(0.5, 3.0)
        weight_col = "_sample_weight"
        return work, weight_col

    raise ValueError(f"Unknown label variant: {variant}")


def phase66_walk_forward(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: list[str],
    *,
    sample_weight_col: str | None = None,
    primary_threshold: float = PRIMARY_THRESHOLD,
    min_train_rows: int = 200,
    min_test_rows: int = 100,
    min_test_trades: int = MIN_TRADES_DEFAULT,
    min_windows: int = 5,
    seed: int = 42,
) -> dict[str, Any]:
    """Strict 5-window walk-forward on TREND with optional sample weights."""
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from tradingbot.ml.research.phase50.strict_walk_forward import _pf
    from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

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

        sw_tr = None
        if sample_weight_col and sample_weight_col in tr.columns:
            sw_tr = tr[sample_weight_col].astype(float).values

        scaler = StandardScaler()
        model = create_trend_ml_model("random_forest", seed=seed)
        model.fit(scaler.fit_transform(X_tr), y_tr, sample_weight=sw_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]

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
        "model": "random_forest",
        "features_used": feature_cols,
        "feature_count": len(feature_cols),
        "primary_threshold": primary_threshold,
        "windows": len(per_year),
        "mean_pf": mean_pf,
        "mean_auc": mean_auc,
        "per_year": per_year,
        "rows_trend": len(work),
    }


def _evaluate_gates(wf: dict[str, Any], *, min_trades_per_window: int = MIN_TRADES_DEFAULT) -> dict[str, Any]:
    from tradingbot.ml.research.phase60.auc_lift_and_validation import _evaluate_gates

    return _evaluate_gates(wf, min_trades_per_window=min_trades_per_window)


def _run_experiment(
    labeled_df: pd.DataFrame,
    *,
    horizon: int,
    variant: str,
    feature_cols: list[str],
    weight_col: str | None,
) -> dict[str, Any]:
    wf = phase66_walk_forward(
        labeled_df,
        "_label",
        feature_cols,
        sample_weight_col=weight_col,
        primary_threshold=PRIMARY_THRESHOLD,
    )
    gates_honest = _evaluate_gates(wf, min_trades_per_window=MIN_TRADES_FLOOR)
    mean_auc = float(wf.get("mean_auc") or 0)
    mean_pf = float(wf.get("mean_pf") or 0)
    honest_pf = float(gates_honest.get("mean_pf_honest") or 0)

    pos_rate = float(labeled_df["_label"].mean()) if len(labeled_df) else 0.0

    return {
        "experiment_id": f"{variant}_h{horizon}",
        "label_variant": variant,
        "horizon_bars": horizon,
        "rows_labeled": int(len(labeled_df)),
        "positive_rate": round(pos_rate, 4),
        "mean_auc": mean_auc,
        "mean_pf": mean_pf,
        "mean_pf_honest": honest_pf,
        "windows_eligible_honest": gates_honest.get("windows_eligible_honest"),
        "gate_passed": bool(wf.get("gate_passed")),
        "gate_passed_honest": bool(gates_honest.get("gate_passed_honest")),
        "auc_gate_pass": mean_auc >= GATE_MEAN_AUC,
        "honest_pf_gate_pass": honest_pf >= GATE_MEAN_PF,
        "delta_auc_vs_baseline": round(mean_auc - BASELINE_AUC, 4),
        "delta_pf_vs_baseline": round(mean_pf - BASELINE_PF, 4),
        "verdict": wf.get("verdict"),
        "walk_forward": wf,
        "gates_honest": gates_honest.get("gates_honest"),
    }


def _pick_best(experiments: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [e for e in experiments if e.get("walk_forward", {}).get("per_year")]
    if not valid:
        return {"experiment_id": "none", "mean_auc": 0.0}

    def score(e: dict[str, Any]) -> tuple:
        return (
            bool(e.get("gate_passed")),
            bool(e.get("gate_passed_honest")),
            float(e.get("mean_auc") or 0),
            float(e.get("mean_pf_honest") or 0),
            float(e.get("mean_pf") or 0),
        )

    return max(valid, key=score)


def _recommendation(best: dict[str, Any], gate_passed: bool) -> dict[str, str]:
    exp_id = best.get("experiment_id", "none")
    variant = best.get("label_variant", "?")
    horizon = best.get("horizon_bars", 72)
    auc = float(best.get("mean_auc") or 0)
    honest = float(best.get("mean_pf_honest") or 0)
    delta = float(best.get("delta_auc_vs_baseline") or 0)

    if gate_passed:
        en = (
            f"Phase 66 best ({exp_id}): AUC {auc:.4f}, honest PF@30={honest:.4f}. "
            f"Carry label={variant}, horizon={horizon} to Phase 67."
        )
        fa = (
            f"بهترین فاز ۶۶ ({exp_id}): AUC {auc:.4f}، PF صادق@30={honest:.4f}. "
            f"label={variant}، horizon={horizon} را به فاز ۶۷ ببرید."
        )
    elif auc >= 0.52 or delta > 0.005:
        en = (
            f"Phase 66 marginal lift ({exp_id}: AUC {auc:.4f}, Δ{delta:+.4f}). "
            f"Honest PF@30={honest:.4f}. Proceed Phase 67 with {variant} @ {horizon} bars."
        )
        fa = (
            f"فاز ۶۶ ارتقای جزئی ({exp_id}: AUC {auc:.4f}، Δ{delta:+.4f}). "
            f"PF صادق@30={honest:.4f}. فاز ۶۷ با {variant} @ {horizon} bar."
        )
    else:
        en = (
            f"Phase 66 label/horizon sweep insufficient (best {exp_id}: AUC {auc:.4f}). "
            f"Honest PF@30={honest:.4f}. Phase 67: ensemble on best available config."
        )
        fa = (
            f"فاز ۶۶ کافی نبود (بهترین {exp_id}: AUC {auc:.4f}). "
            f"PF صادق@30={honest:.4f}. فاز ۶۷: ensemble با بهترین کانفیگ."
        )
    return {"en": en, "fa": fa}


def run_phase66(*, force_relabel: bool = False, sample_frac: float | None = None) -> dict[str, Any]:
    if force_relabel and LABEL_CACHE.is_dir():
        for p in LABEL_CACHE.glob("horizon_*.parquet"):
            p.unlink()

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "v7 parquet missing"}

    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles

    raw = pd.read_parquet(V7_PATH)
    candles = resolve_fullest_candles()
    if candles is None or candles.empty:
        return {"verdict": "INSUFFICIENT_DATA", "error": "candles missing"}

    feature_cols = [c for c in _load_baseline_features() if c in raw.columns]
    relabel_note = "full TREND subset"
    if sample_frac is not None:
        relabel_note = f"sampled {sample_frac:.0%} per year (stratified)"

    horizon_frames: dict[int, pd.DataFrame] = {}
    relabel_stats: list[dict[str, Any]] = []

    for h in HORIZONS:
        print(f"  relabeling horizon={h}...", flush=True)
        t0 = time.time()
        frame = relabel_at_horizon(
            raw, candles, future_window_bars=h, sample_frac=sample_frac,
        )
        horizon_frames[h] = frame
        tp = int((frame["resolved_label"] == 1).sum())
        sl = int((frame["resolved_label"] == 0).sum())
        nr = int((frame["resolved_label"] == -1).sum())
        relabel_stats.append({
            "horizon_bars": h,
            "rows": len(frame),
            "tp_first": tp,
            "sl_first": sl,
            "no_resolution": nr,
            "positive_rate_v3": round(tp / max(tp + sl, 1), 4),
            "elapsed_sec": round(time.time() - t0, 1),
        })

    experiments: list[dict[str, Any]] = []
    total = len(HORIZONS) * len(LABEL_VARIANTS)
    done = 0

    for h in HORIZONS:
        frame = horizon_frames[h]
        for variant in LABEL_VARIANTS:
            done += 1
            use_existing = variant == "label_v3" and h == 72 and sample_frac is None
            labeled, weight_col = apply_label_variant(frame, variant, use_existing_v3=use_existing)
            print(
                f"  WF [{done}/{total}] {variant} h={h} rows={len(labeled)}",
                flush=True,
            )
            exp = _run_experiment(
                labeled, horizon=h, variant=variant,
                feature_cols=feature_cols, weight_col=weight_col,
            )
            experiments.append(exp)

    best = _pick_best(experiments)
    auc_gate = bool(best.get("auc_gate_pass"))
    honest_gate = bool(best.get("honest_pf_gate_pass"))
    overall_gate = bool(best.get("gate_passed")) and honest_gate

    if overall_gate:
        verdict = "STRICT_GATE_PASS"
    elif float(best.get("mean_auc") or 0) >= 0.52:
        verdict = "STRICT_GATE_MARGINAL"
    else:
        verdict = "STRICT_GATE_FAIL"

    comparison = [
        {
            "experiment_id": e["experiment_id"],
            "label_variant": e["label_variant"],
            "horizon_bars": e["horizon_bars"],
            "rows_labeled": e["rows_labeled"],
            "positive_rate": e["positive_rate"],
            "mean_auc": e["mean_auc"],
            "mean_pf": e["mean_pf"],
            "mean_pf_honest": e["mean_pf_honest"],
            "delta_auc_vs_baseline": e["delta_auc_vs_baseline"],
            "auc_gate_pass": e["auc_gate_pass"],
            "honest_pf_gate_pass": e["honest_pf_gate_pass"],
            "verdict": e["verdict"],
        }
        for e in experiments
    ]

    rec = _recommendation(best, overall_gate)

    horizon_only = [
        e for e in comparison if e["label_variant"] == "label_v3"
    ]
    variant_at_72 = [
        e for e in comparison if e["horizon_bars"] == 72
    ]

    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "gate_passed": overall_gate,
        "auc_gate_pass": auc_gate,
        "honest_pf_gate_pass": honest_gate,
        "gate_targets": {
            "mean_auc": GATE_MEAN_AUC,
            "honest_pf": GATE_MEAN_PF,
            "min_trades": MIN_TRADES_FLOOR,
        },
        "baseline": {
            "config": "baseline_rf_10f_label_v3_h72",
            "mean_auc": BASELINE_AUC,
            "mean_pf": BASELINE_PF,
            "mean_pf_honest": BASELINE_HONEST_PF,
        },
        "relabel_method": {
            "function": "resolve_label_with_sl_tp",
            "candles": "resolve_fullest_candles (phase39)",
            "horizons": HORIZONS,
            "note": relabel_note,
            "stats": relabel_stats,
        },
        "label_variants": list(LABEL_VARIANTS),
        "experiments": experiments,
        "comparison": comparison,
        "horizon_sweep_label_v3": horizon_only,
        "variant_comparison_at_h72": variant_at_72,
        "best_config": {
            "experiment_id": best.get("experiment_id"),
            "label_variant": best.get("label_variant"),
            "horizon_bars": best.get("horizon_bars"),
            "mean_auc": best.get("mean_auc"),
            "mean_pf": best.get("mean_pf"),
            "mean_pf_honest": best.get("mean_pf_honest"),
            "delta_auc_vs_baseline": best.get("delta_auc_vs_baseline"),
            "primary_threshold": PRIMARY_THRESHOLD,
            "features": feature_cols,
            "for_phase_67_68": {
                "label_variant": best.get("label_variant"),
                "horizon_bars": best.get("horizon_bars"),
                "features": feature_cols,
                "threshold": PRIMARY_THRESHOLD,
                "model": "random_forest",
            },
        },
        "recommendation_en": rec["en"],
        "recommendation_fa": rec["fa"],
        "next_phase": "67",
        "research_only": True,
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    slim_experiments = [
        {k: v for k, v in e.items() if k != "walk_forward"}
        for e in data.get("experiments", [])
    ]
    artifact = {
        "relabel_method": data.get("relabel_method"),
        "comparison": data.get("comparison"),
        "horizon_sweep_label_v3": data.get("horizon_sweep_label_v3"),
        "variant_comparison_at_h72": data.get("variant_comparison_at_h72"),
        "best_config": data.get("best_config"),
        "experiments_summary": slim_experiments,
    }
    (ARTIFACTS / "label_horizon_experiments.json").write_text(
        json.dumps(artifact, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase66/artifacts/label_horizon_experiments.json", flush=True)

    best = data.get("best_config") or {}
    report = {
        "phase": "66",
        "title": "Label & Horizon Experiments",
        "title_fa": "آزمایش برچسب و افق زمانی",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "gate_passed": data.get("gate_passed"),
        "auc_gate_pass": data.get("auc_gate_pass"),
        "honest_pf_gate_pass": data.get("honest_pf_gate_pass"),
        "gate_targets": data.get("gate_targets"),
        "baseline": data.get("baseline"),
        "relabel_method": data.get("relabel_method"),
        "label_variants": data.get("label_variants"),
        "comparison": data.get("comparison"),
        "horizon_sweep_label_v3": data.get("horizon_sweep_label_v3"),
        "variant_comparison_at_h72": data.get("variant_comparison_at_h72"),
        "best_config": best,
        "mean_auc": best.get("mean_auc"),
        "mean_pf": best.get("mean_pf"),
        "mean_pf_honest": best.get("mean_pf_honest"),
        "delta_auc_vs_baseline": best.get("delta_auc_vs_baseline"),
        "primary_threshold": PRIMARY_THRESHOLD,
        "for_phase_67_68": best.get("for_phase_67_68"),
        "recommendation_en": data.get("recommendation_en"),
        "recommendation_fa": data.get("recommendation_fa"),
        "next_phase": data.get("next_phase"),
    }
    (ROOT / "phase66_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase66_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    best = data.get("best_config") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_66_COMPLETE"
    status["current_treatment_phase"] = "66"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["66"] = {
        "status": "COMPLETE",
        "track": "M",
        "verdict": report.get("verdict"),
        "report": "phase66_final_report.json",
        "gate_passed": bool(report.get("gate_passed")),
    }
    status["phase66_summary"] = {
        "best_experiment": best.get("experiment_id"),
        "label_variant": best.get("label_variant"),
        "horizon_bars": best.get("horizon_bars"),
        "mean_auc": best.get("mean_auc"),
        "mean_pf": best.get("mean_pf"),
        "mean_pf_honest": best.get("mean_pf_honest"),
        "delta_auc_vs_baseline": best.get("delta_auc_vs_baseline"),
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
        if str(ph.get("phase")) == "66":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "67"
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Phase 66 label/horizon experiments")
    p.add_argument("--force-relabel", action="store_true", help="Clear relabel cache")
    p.add_argument("--sample-frac", type=float, default=None, help="Sample fraction per year if slow")
    args = p.parse_args()

    data = run_phase66(force_relabel=args.force_relabel, sample_frac=args.sample_frac)
    write_all(data)
    best = data.get("best_config") or {}
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "gate_passed": data.get("gate_passed"),
                "best": best.get("experiment_id"),
                "mean_auc": best.get("mean_auc"),
                "mean_pf_honest": best.get("mean_pf_honest"),
                "delta_auc": best.get("delta_auc_vs_baseline"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
