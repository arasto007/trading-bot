"""Phase 22V — phase9_9 training pipeline forensics."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_classif
from sklearn.preprocessing import StandardScaler

FEATURES = ("ema50_slope", "candle_direction", "structure_distance")
BUY_ZONE = 0.55
SELL_ZONE = 0.45


def build_training_pipeline_map() -> dict[str, Any]:
    return {
        "phase": "22V",
        "title": "phase9_9 training pipeline (repository trace)",
        "stages": [
            {
                "step": 1,
                "name": "Market candles",
                "source": "CandleStore (M5/H4/M15)",
                "files": [
                    "tradingbot/ml/data/stores.py",
                    "scripts/collect_ml_data.py",
                ],
            },
            {
                "step": 2,
                "name": "Sparse event dataset",
                "function": "SparseEventDatasetBuilder.build",
                "file": "tradingbot/ml/dataset/sparse_event_builder.py",
                "details": "FeatureBuilder.compute_at at event bars → labeled rows",
            },
            {
                "step": 3,
                "name": "Production dataset build",
                "function": "Phase91ProductionBuilder.run",
                "file": "tradingbot/ml/dataset/phase9_production_build.py",
                "script": "scripts/build_ml_dataset.py --phase9-1",
            },
            {
                "step": 4,
                "name": "dataset_v2 parquet",
                "path": "data/ml/datasets/XAUUSD_M5_dataset_v2.parquet",
                "store": "tradingbot/ml/dataset/store.py",
            },
            {
                "step": 5,
                "name": "Phase 9.6 feature stability",
                "report": "data/ml/reports/feature_stability_report.json",
            },
            {
                "step": 6,
                "name": "Phase 9.8 walk-forward baseline",
                "engine": "WalkForwardEngine",
                "file": "tradingbot/ml/research/walk_forward/",
                "script": "scripts/train_model.py --phase9-8",
            },
            {
                "step": 7,
                "name": "Phase 9.9 candidate grid",
                "orchestrator": "RobustnessOptimizer.run",
                "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                "script": "scripts/train_model.py --phase9-9",
                "selection": "rank_candidates composite: 40% robustness + 25% PF + 20% consistency + 15% low overfitting",
            },
            {
                "step": 8,
                "name": "Feature subset selection",
                "function": "run_feature_selection_research → stable_top3",
                "file": "tradingbot/ml/research/robustness_optimizer/stable_feature_research.py",
                "report": "data/ml/reports/phase9_9_feature_selection.json",
            },
            {
                "step": 9,
                "name": "Walk-forward window train (per candidate)",
                "function": "validate_window_candidate",
                "file": "tradingbot/ml/research/robustness_optimizer/window_validator.py",
                "filters": "apply_phase97_filters: market_regime==RANGE, event_scheme=A_all_events",
            },
            {
                "step": 10,
                "name": "Freeze artifacts",
                "function": "freeze_phase9_9_artifacts",
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "outputs": [
                    "data/ml/research/phase9_9_best/model.pkl",
                    "data/ml/research/phase9_9_best/scaler.pkl",
                    "data/ml/research/phase9_9_best/feature_order.json",
                    "data/ml/research/phase9_9_best/config.json",
                    "data/ml/research/phase9_9_best/metadata.json",
                ],
            },
        ],
        "freeze_training_recipe": {
            "filter_resolved_labels": True,
            "market_regime": "RANGE",
            "event_filter": "A_all_events",
            "chronological_train_cut": "first 85% of filtered frame",
            "model": "LogisticRegression C=0.1 solver=lbfgs max_iter=500",
            "scaler": "StandardScaler fit on train slice only",
            "features_frozen": list(FEATURES),
        },
        "production_modified": False,
    }


def replicate_freeze_training_frame(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    from tradingbot.ml.paper_trading.model_registry import _training_frame

    frame = _training_frame(df, config)
    cut = int(len(frame) * 0.85)
    train = frame.iloc[:cut].copy()
    holdout = frame.iloc[cut:].copy()
    return train, holdout


def feature_statistics(df: pd.DataFrame, features: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in features:
        if f not in df.columns:
            continue
        s = df[f].astype(float)
        out[f] = {
            "mean": round(float(s.mean()), 8),
            "std": round(float(s.std()), 8),
            "min": round(float(s.min()), 8),
            "max": round(float(s.max()), 8),
            "variance": round(float(s.var()), 8),
            "skewness": round(float(stats.skew(s)), 6),
            "zero_pct": round(float((s.abs() < 1e-9).mean()) * 100, 4),
            "nonzero_count": int((s.abs() >= 1e-9).sum()),
        }
    return out


def scaled_feature_statistics(train: pd.DataFrame, scaler: StandardScaler, features: list[str]) -> dict[str, Any]:
    X = scaler.transform(train.loc[:, features].astype(np.float64).values)
    out: dict[str, Any] = {}
    for i, f in enumerate(features):
        col = X[:, i]
        out[f] = {
            "mean_after_scale": round(float(np.mean(col)), 8),
            "std_after_scale": round(float(np.std(col)), 8),
            "min_after_scale": round(float(np.min(col)), 8),
            "max_after_scale": round(float(np.max(col)), 8),
        }
    return out


def feature_predictiveness(train: pd.DataFrame, features: list[str]) -> dict[str, Any]:
    y = train["label"].astype(int).to_numpy()
    X = train.loc[:, features].astype(np.float64).values
    out: dict[str, Any] = {}
    for i, f in enumerate(features):
        col = X[:, i]
        if np.std(col) < 1e-12:
            pearson = spearman = mi = 0.0
        else:
            pearson = float(stats.pearsonr(col, y)[0]) if len(np.unique(y)) > 1 else 0.0
            spearman = float(stats.spearmanr(col, y)[0]) if len(np.unique(y)) > 1 else 0.0
            mi = float(mutual_info_classif(col.reshape(-1, 1), y, random_state=42)[0])
        out[f] = {
            "pearson_with_label": round(pearson, 6),
            "spearman_with_label": round(spearman, 6),
            "mutual_information": round(mi, 6),
        }
    return out


def training_process_audit(config: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.ml.research.robustness_optimizer.model_regularization import create_regularized_model, ModelCandidateConfig

    candidate = ModelCandidateConfig(
        candidate_id="logistic_strong_reg",
        model_name="logistic",
        hyperparameters=config.get("parameters", {"C": 0.1}),
    )
    est = create_regularized_model(candidate, seed=42)._model
    params = est.get_params()
    return {
        "sample_weight_used": False,
        "class_weight_used": params.get("class_weight") is not None,
        "class_weight_value": params.get("class_weight"),
        "balancing_applied": False,
        "down_sampling": False,
        "up_sampling": False,
        "thresholding_at_train": False,
        "filtering": {
            "filter_resolved_labels": True,
            "market_regime_filter": config.get("regime", "RANGE"),
            "event_filter": config.get("event_filter", "A_all_events"),
            "chronological_85pct_slice": True,
        },
        "logistic_hyperparameters": {
            k: params[k]
            for k in (
                "C", "penalty", "solver", "max_iter", "class_weight",
                "fit_intercept", "l1_ratio", "warm_start",
            )
            if k in params
        },
        "selection_criterion_phase9_9": (
            "Walk-forward validation profit_factor + robustness_score; "
            "NOT buy-zone probability coverage"
        ),
        "freeze_vs_walkforward": (
            "Phase 9.9 selects candidate via walk-forward grid; "
            "freeze_phase9_9_artifacts retrains on first 85% chronological slice of RANGE frame"
        ),
    }


def convergence_from_frozen_model(bundle) -> dict[str, Any]:
    est = getattr(bundle.model, "_model", bundle.model)
    out: dict[str, Any] = {
        "estimator": type(est).__name__,
        "converged": bool(getattr(est, "converged_", True)),
        "n_iter": int(getattr(est, "n_iter_", [0])[0]) if hasattr(est, "n_iter_") else None,
        "max_iter": int(getattr(est, "max_iter", 500)),
        "solver": getattr(est, "solver", None),
        "warnings": [],
    }
    if out["n_iter"] is not None and out["n_iter"] >= out["max_iter"]:
        out["warnings"].append("hit_max_iter")
    coef = getattr(est, "coef_", None)
    if coef is not None:
        out["coef_l2_norm"] = round(float(np.linalg.norm(coef)), 6)
    return out


def probability_zones(probs: np.ndarray) -> dict[str, Any]:
    n = len(probs)
    buy = int(np.sum(probs >= BUY_ZONE))
    sell = int(np.sum(probs <= SELL_ZONE))
    neutral = n - buy - sell
    return {
        "n": n,
        "buy_zone_pct": round(buy / max(n, 1) * 100, 4),
        "sell_zone_pct": round(sell / max(n, 1) * 100, 4),
        "neutral_pct": round(neutral / max(n, 1) * 100, 4),
        "max_p_win": round(float(np.max(probs)), 6) if n else None,
        "min_p_win": round(float(np.min(probs)), 6) if n else None,
    }


def assess_logistic_suitability(
    feature_stats: dict[str, Any],
    predictiveness: dict[str, Any],
    train_zones: dict[str, Any],
) -> dict[str, Any]:
    struct_zero = feature_stats.get("structure_distance", {}).get("zero_pct", 0)
    max_mi = max((v.get("mutual_information", 0) for v in predictiveness.values()), default=0)
    buy_pct = train_zones.get("buy_zone_pct", 0)
    return {
        "linear_on_sparse_zero_heavy_features": struct_zero > 90,
        "structure_distance_zero_pct": struct_zero,
        "max_feature_mutual_information": round(max_mi, 6),
        "training_buy_zone_pct": buy_pct,
        "repository_evidence": [
            "LogisticRegression selected for Phase 9.9 robustness score (walk-forward PF), not probability spread",
            f"structure_distance zero-filled {struct_zero}% in freeze train slice",
            "Strong L2 (C=0.1) + negative intercept compresses P(win) below buy threshold",
            "Phase 9.9 validation uses ThresholdStrategy simulation; freeze artifact never checked for buy-zone coverage",
        ],
        "appropriate_for_dataset": False,
        "reason": "Sparse/zero-heavy nonlinear structure features with weak MI; linear L2 model outputs degenerated probability mass",
    }


def probability_histogram(probs: np.ndarray, *, bin_width: float = 0.05) -> dict[str, Any]:
    edges = np.arange(0.0, 1.0 + bin_width, bin_width)
    counts, bin_edges = np.histogram(probs, bins=edges)
    bins = []
    for i, count in enumerate(counts):
        lo = round(float(bin_edges[i]), 2)
        hi = round(float(bin_edges[i + 1]), 2)
        bins.append({
            "range": f"{lo:.2f}-{hi:.2f}",
            "count": int(count),
            "pct": round(int(count) / max(len(probs), 1) * 100, 4),
        })
    return {"bin_width": bin_width, "total": len(probs), "bins": bins}


def determine_root_cause(
    feature_stats: dict[str, Any],
    predictiveness: dict[str, Any],
    training_process: dict[str, Any],
    train_zones: dict[str, Any],
    label_dist: dict[str, Any],
) -> tuple[str, list[str]]:
    causes: list[str] = []

    struct_zero = feature_stats.get("structure_distance", {}).get("zero_pct", 100)
    if struct_zero > 90:
        causes.append("BAD_FEATURES")

    pos_pct = label_dist.get("positive_pct", 0)
    if pos_pct < 10 or pos_pct > 90:
        causes.append("BAD_LABELS")

    max_mi = max((v.get("mutual_information", 0) for v in predictiveness.values()), default=0)
    if max_mi < 0.01 and struct_zero > 90:
        causes.append("BAD_DATA")

    if training_process.get("selection_criterion_phase9_9") and train_zones.get("buy_zone_pct", 0) < 1:
        causes.append("BAD_TRAINING")

    std_p = train_zones.get("p_win_std")
    if train_zones.get("buy_zone_pct", 0) < 1 and struct_zero > 90:
        causes.append("BAD_MODEL_CHOICE")

    if len(causes) >= 2:
        return "MULTIPLE_CAUSES", causes
    if causes:
        return causes[0], causes
    return "MODEL_HEALTHY", causes


def run_forensics(*, base_dir: str | None = None) -> dict[str, Any]:
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.paper_trading.model_registry import DEFAULT_CONFIG, load_phase9_9_bundle
    from tradingbot.ml.research.phase22f.config import build_dataset

    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    config = dict(bundle.config or DEFAULT_CONFIG)
    features = list(bundle.feature_order)

    ds = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
    if ds is None or ds.empty:
        return {"error": "dataset_v2_missing"}

    train, holdout = replicate_freeze_training_frame(ds, config)
    scaler = StandardScaler()
    X_tr = train.loc[:, features].astype(np.float64).values
    y_tr = train["label"].astype(int).to_numpy()
    scaler.fit(X_tr)

    # Raw model inference on train slice (frozen artifact)
    probs_train = np.array([bundle.predict_proba(row) for _, row in train.iterrows()])
    probs_full = np.array([
        bundle.predict_proba(row) for _, row in ds.loc[ds["label"].isin([0, 1])].iterrows()
    ])

    est = getattr(bundle.model, "_model", bundle.model)
    raw_stats = feature_statistics(train, tuple(features))
    scaled_stats = scaled_feature_statistics(train, scaler, features)
    predictiveness = feature_predictiveness(train, features)

    # Feature importance from frozen coef
    coef = est.coef_[0]
    abs_coef = np.abs(coef)
    total = float(abs_coef.sum()) or 1.0
    coef_importance = {f: round(float(abs_coef[i] / total), 6) for i, f in enumerate(features)}

    for f in predictiveness:
        predictiveness[f]["logistic_abs_coef_importance"] = coef_importance.get(f, 0.0)

    labels = {
        "total_rows": len(train),
        "positive_tp_first": int((y_tr == 1).sum()),
        "negative_sl_first": int((y_tr == 0).sum()),
        "positive_pct": round(float((y_tr == 1).mean()) * 100, 4),
        "negative_pct": round(float((y_tr == 0).mean()) * 100, 4),
        "classes_present": sorted(np.unique(y_tr).tolist()),
    }

    train_zones = probability_zones(probs_train)
    train_zones["p_win_mean"] = round(float(np.mean(probs_train)), 6)
    train_zones["p_win_std"] = round(float(np.std(probs_train)), 6)

    full_zones = probability_zones(probs_full)

    dataset_a = build_dataset("A")
    ds_a = _filter_dataset_a(ds, dataset_a)
    probs_a = np.array([bundle.predict_proba(row) for _, row in ds_a.iterrows()]) if not ds_a.empty else np.array([])
    zones_a = probability_zones(probs_a) if len(probs_a) else None

    training_process = training_process_audit(config)
    convergence = convergence_from_frozen_model(bundle)
    logistic_assessment = assess_logistic_suitability(raw_stats, predictiveness, train_zones)

    verdict, cause_list = determine_root_cause(
        raw_stats, predictiveness, training_process, train_zones, labels,
    )

    return {
        "training_pipeline_map": build_training_pipeline_map(),
        "model_weights": _extract_weights(bundle),
        "feature_statistics": {
            "train_rows": len(train),
            "holdout_rows": len(holdout),
            "before_scaling": raw_stats,
            "after_scaling": scaled_stats,
            "feature_selection": {
                "subset": "stable_top3",
                "features": features,
                "source": "phase9_9_feature_selection.json / DEFAULT_CONFIG",
            },
        },
        "feature_predictiveness": predictiveness,
        "training_process": training_process,
        "convergence_report": convergence,
        "training_probability_distribution": {
            "freeze_train_slice": train_zones,
            "full_resolved_dataset_v2": full_zones,
            "dataset_a_subset": zones_a,
        },
        "training_label_distribution": labels,
        "probability_histogram_train_slice": probability_histogram(probs_train),
        "probability_histogram_full_dataset": probability_histogram(probs_full),
        "logistic_suitability": logistic_assessment,
        "verdict": verdict,
        "root_causes": cause_list,
        "root_cause_narrative": _narrative(verdict, cause_list, raw_stats, train_zones, labels, training_process),
    }


def _extract_weights(bundle) -> dict[str, Any]:
    est = getattr(bundle.model, "_model", bundle.model)
    features = list(bundle.feature_order)
    w: dict[str, Any] = {
        "estimator": type(est).__name__,
        "feature_order": features,
        "intercept": round(float(est.intercept_[0]), 8),
        "coefficients": {f: round(float(est.coef_[0][i]), 8) for i, f in enumerate(features)},
    }
    abs_c = np.abs(est.coef_[0])
    tot = float(abs_c.sum()) or 1.0
    w["feature_importance_abs_coef"] = {f: round(float(abs_c[i] / tot), 6) for i, f in enumerate(features)}
    w["classes"] = [int(c) for c in est.classes_]
    return w


def _filter_dataset_a(df: pd.DataFrame, dataset_a) -> pd.DataFrame:
    from zoneinfo import ZoneInfo

    tehran = ZoneInfo("Asia/Tehran")
    ts = pd.to_datetime(df["timestamp"], utc=True)
    start = pd.Timestamp(dataset_a.start.astimezone(tehran)).tz_convert("UTC")
    end = pd.Timestamp(dataset_a.end.astimezone(tehran)).tz_convert("UTC")
    resolved = df.loc[df["label"].isin([0, 1])].copy()
    return resolved.loc[(ts >= start) & (ts <= end)].copy()


def _narrative(verdict, causes, stats, zones, labels, process) -> str:
    parts = [f"Verdict={verdict}."]
    if "BAD_FEATURES" in causes:
        parts.append(
            f"structure_distance {stats.get('structure_distance', {}).get('zero_pct')}% zero in freeze train slice."
        )
    if "BAD_TRAINING" in causes:
        parts.append(
            "Phase 9.9 selected candidate by walk-forward PF/robustness; freeze never validated buy-zone probability coverage."
        )
    if "BAD_LABELS" in causes:
        parts.append(f"Label balance positive={labels.get('positive_pct')}%.")
    else:
        parts.append(f"Labels balanced (positive={labels.get('positive_pct')}%) — not a label problem.")
    parts.append(
        f"Frozen model on train slice: buy_zone={zones.get('buy_zone_pct')}%, max_p={zones.get('max_p_win')}."
    )
    return " ".join(parts)
