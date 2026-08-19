"""Phase 9.5 — experimental model training and comparison."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import (
    advanced_discovery_dataset_path,
    advanced_discovery_datasets_root,
    phase9_4_retraining_report_path,
    training_comparison_report_path,
)
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.advanced_discovery.experimental_features import (
    EXPERIMENTAL_FEATURE_NAMES,
    compute_experimental_features,
)
from tradingbot.ml.research.label_experiment import relabel_dataframe
from tradingbot.ml.research.model_selection import ModelCandidate, ModelSelector
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.training.data_loader import (
    TrainingSplits,
    assert_no_test_leakage,
    filter_resolved_labels,
)
from tradingbot.ml.training.evaluation import TrainingEvaluator
from tradingbot.ml.training.model_factory import DEFAULT_SEED

RESEARCH_MODELS = ("logistic", "random_forest", "xgboost", "lightgbm")


@dataclass
class DiscoveryExperiment:
    experiment_id: str
    description: str
    feature_columns: list[str]
    label_config: dict[str, Any]
    event_filter: tuple[str, ...] | None


def _load_baseline_reports(base_dir: str | Path | None) -> dict[str, Any]:
    phase92: dict[str, Any] = {}
    phase94: dict[str, Any] = {}
    p92_path = training_comparison_report_path(base_dir)
    p94_path = phase9_4_retraining_report_path(base_dir)
    if p92_path.is_file():
        phase92 = json.loads(p92_path.read_text(encoding="utf-8"))
    if p94_path.is_file():
        phase94 = json.loads(p94_path.read_text(encoding="utf-8"))
    return {"phase9_2": phase92, "phase9_4": phase94}


def _baseline_val_auc(baselines: dict[str, Any], phase: str) -> float:
    if phase == "phase9_2":
        best = baselines.get("phase9_2", {}).get("best_model", "")
        ev = baselines.get("phase9_2", {}).get("evaluations", {}).get(best, {})
        return float(ev.get("validation", {}).get("classification", {}).get("roc_auc", 0.0))
    best = baselines.get("phase9_4", {}).get("best_model", {})
    if isinstance(best, dict):
        return float(best.get("validation_metrics", {}).get("classification", {}).get("roc_auc", 0.0))
    val = baselines.get("phase9_4", {}).get("summary", {}).get("validation_roc_auc", 0.0)
    return float(val or 0.0)


def build_discovery_frame(
    source: pd.DataFrame,
    *,
    candles: pd.DataFrame | None,
    label_config: dict[str, Any] | None,
    event_filter: tuple[str, ...] | None,
    include_experimental: bool,
    extra_features: list[str] | None = None,
) -> pd.DataFrame:
    work = source.copy()
    if event_filter:
        work = work.loc[work["event_type"].isin(event_filter)].copy()
    if label_config and label_config.get("relabel_applied") and candles is not None:
        work = relabel_dataframe(
            work,
            candles,
            atr_period=int(label_config["atr_period"]),
            tp_r=float(label_config["tp_r_multiple"]),
            future_window_bars=int(label_config["future_window_bars"]),
        )
    if include_experimental:
        work = compute_experimental_features(work)
    work = filter_resolved_labels(work)
    return work


def _feature_list(
    df: pd.DataFrame,
    *,
    top_registry: list[str],
    include_experimental: bool,
) -> list[str]:
    dead = {"spread_spike"}
    registry = [f for f in top_registry if f in df.columns and f not in dead]
    if not registry:
        registry = [f for f in feature_names() if f in df.columns and f not in dead]
    cols = list(registry)
    if include_experimental:
        cols.extend([f for f in EXPERIMENTAL_FEATURE_NAMES if f in df.columns])
    return cols


def splits_from_discovery_df(df: pd.DataFrame, feature_cols: list[str], symbol: str, tf: str) -> TrainingSplits:
    train_df = df.loc[df["split"] == "train"].reset_index(drop=True)
    val_df = df.loc[df["split"] == "validation"].reset_index(drop=True)
    test_df = df.loc[df["split"] == "test"].reset_index(drop=True)
    for name, part in ("train", train_df), ("validation", val_df), ("test", test_df):
        if len(part) < 10:
            raise ValueError(f"Discovery split {name} too small: {len(part)} rows")
    splits = TrainingSplits(
        train=train_df,
        validation=val_df,
        test=test_df,
        feature_columns=tuple(feature_cols),
        symbol=symbol.upper(),
        timeframe=tf.upper(),
    )
    assert_no_test_leakage(splits)
    return splits


def _train_experiment(
    splits: TrainingSplits,
    experiment_id: str,
    *,
    seed: int,
    hyperparameters: dict[str, dict[str, Any]],
) -> list[ModelCandidate]:
    scaler = StandardScaler()
    X_train, y_train = splits.train_xy()
    scaler.fit(X_train.astype(np.float64).values)
    arrays: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for name in ("train", "validation", "test"):
        X, y = splits.feature_matrix(name)
        X_s = scaler.transform(X.astype(np.float64).values)
        arrays[name] = (X_s, y.to_numpy(dtype=int))

    evaluator = TrainingEvaluator()
    candidates: list[ModelCandidate] = []
    X_tr, y_tr = arrays["train"]
    X_va, y_va = arrays["validation"]
    X_te, y_te = arrays["test"]

    for model_name in RESEARCH_MODELS:
        hp = hyperparameters.get(model_name, {})
        model = create_research_model(model_name, seed, hp)
        model.fit(X_tr, y_tr, eval_set=(X_va, y_va))
        val_m = evaluator.evaluate(model, X_va, y_va, split="validation")
        test_m = evaluator.evaluate(model, X_te, y_te, split="test")
        candidates.append(
            ModelCandidate(
                model_name=model_name,
                variant_id=experiment_id,
                validation=val_m,
                test=test_m,
                hyperparameters=hp,
            )
        )
    return candidates


def run_model_discovery(
    source: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    candles: pd.DataFrame | None,
    top_features: list[str],
    best_label: dict[str, Any] | None,
    best_event: str | None,
    base_dir: str | Path | None,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Train discovery candidates and compare against Phase 9.2 / 9.4 baselines."""
    baselines = _load_baseline_reports(base_dir)
    hyperparameters = _load_tuned_hyperparameters(base_dir)

    experiments: list[DiscoveryExperiment] = [
        DiscoveryExperiment(
            experiment_id="registry_plus_experimental",
            description="Top registry + experimental features, original labels",
            feature_columns=[],
            label_config={"relabel_applied": False},
            event_filter=None,
        ),
        DiscoveryExperiment(
            experiment_id="best_label_experimental",
            description="Best label config + experimental features",
            feature_columns=[],
            label_config={
                "relabel_applied": True,
                "atr_period": int((best_label or {}).get("atr_period", 20)),
                "tp_r_multiple": float((best_label or {}).get("tp_r_multiple", 2.0)),
                "future_window_bars": int((best_label or {}).get("future_window_bars", 120)),
            },
            event_filter=tuple(best_label["event_filter"]) if best_label and best_label.get("event_filter") else None,
        ),
    ]
    if best_event:
        experiments.append(
            DiscoveryExperiment(
                experiment_id=f"event_{best_event}",
                description=f"Focus on best event {best_event} with experimental features",
                feature_columns=[],
                label_config={"relabel_applied": False},
                event_filter=(best_event,),
            )
        )

    selector = ModelSelector()
    all_candidates: list[ModelCandidate] = []
    saved_paths: dict[str, str] = {}
    experiment_summaries: list[dict[str, Any]] = []

    advanced_discovery_datasets_root(base_dir).mkdir(parents=True, exist_ok=True)

    for exp in experiments:
        try:
            include_exp = True
            frame = build_discovery_frame(
                source,
                candles=candles,
                label_config=exp.label_config if exp.label_config.get("relabel_applied") else None,
                event_filter=exp.event_filter,
                include_experimental=include_exp,
            )
            cols = _feature_list(frame, top_registry=top_features, include_experimental=include_exp)
            splits = splits_from_discovery_df(frame, cols, symbol, timeframe)
            path = advanced_discovery_dataset_path(symbol, timeframe, exp.experiment_id, base_dir)
            frame.to_parquet(path, index=False)
            saved_paths[exp.experiment_id] = str(path)
            candidates = _train_experiment(splits, exp.experiment_id, seed=seed, hyperparameters=hyperparameters)
            all_candidates.extend(candidates)
            best = selector.select_best(candidates)
            experiment_summaries.append(
                {
                    "experiment_id": exp.experiment_id,
                    "description": exp.description,
                    "row_count": len(frame),
                    "feature_count": len(cols),
                    "best_model": best.model_name,
                    "validation_roc_auc": best.validation.classification.get("roc_auc"),
                    "test_roc_auc": best.test.classification.get("roc_auc"),
                }
            )
        except Exception as exc:
            experiment_summaries.append(
                {"experiment_id": exp.experiment_id, "error": str(exc)},
            )

    if not all_candidates:
        return {"candidates": [], "error": "no successful discovery experiments"}

    best = selector.select_best(all_candidates)
    val_auc = float(best.validation.classification.get("roc_auc", 0.0))
    test_auc = float(best.test.classification.get("roc_auc", 0.0))

    return {
        "phase": "9.5",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiments": experiment_summaries,
        "comparison_table": selector.comparison_table(all_candidates),
        "best_candidate": best.to_dict(),
        "baseline_phase9_2_val_roc_auc": _baseline_val_auc(baselines, "phase9_2"),
        "baseline_phase9_4_val_roc_auc": _baseline_val_auc(baselines, "phase9_4"),
        "beats_phase9_2": val_auc > _baseline_val_auc(baselines, "phase9_2"),
        "beats_phase9_4": val_auc > _baseline_val_auc(baselines, "phase9_4"),
        "validation_roc_auc": val_auc,
        "test_roc_auc": test_auc,
        "saved_datasets": saved_paths,
    }


def _load_tuned_hyperparameters(base_dir: str | Path | None) -> dict[str, dict[str, Any]]:
    from tradingbot.ml.data.paths import model_optimization_report_path

    path = model_optimization_report_path(base_dir)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {m["model"]: m.get("best_params", {}) for m in payload.get("models", [])}
