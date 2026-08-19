"""Phase 9.4 — research-based retraining and optimization (isolated from production pipeline)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import (
    experimental_dataset_path,
    feature_importance_report_path,
    model_optimization_report_path,
    phase9_3_research_report_path,
    research_datasets_root,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.label_experiment import (
    RESEARCH_ATR_PERIOD,
    RESEARCH_FUTURE_WINDOW,
    RESEARCH_TP_R,
    relabel_dataframe,
)
from tradingbot.ml.research.model_selection import ModelCandidate, ModelSelector
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.retrain_report import build_retraining_report, save_retraining_report
from tradingbot.ml.training.data_loader import (
    TrainingSplits,
    assert_no_test_leakage,
    filter_resolved_labels,
    validate_training_splits,
)
from tradingbot.ml.training.evaluation import TrainingEvaluator
from tradingbot.ml.training.model_factory import DEFAULT_SEED, TrainingModel, create_training_model

logger = logging.getLogger(__name__)

PHASE = "9.4"
RESEARCH_MODELS = ("logistic", "random_forest", "xgboost", "lightgbm")

DEAD_FEATURES: frozenset[str] = frozenset({"spread_spike"})
LOW_CONTRIBUTION_FEATURES: frozenset[str] = frozenset({"engulfing_flag", "session_asia"})
EXCLUDED_EVENT_TYPES: frozenset[str] = frozenset({"trading_session"})
HIGH_VALUE_EVENT_TYPES: frozenset[str] = frozenset(
    {"order_block", "choch", "fvg", "liquidity_sweep", "session_transition"}
)
TOP_FEATURE_COUNT = 15


@dataclass
class ResearchScaler:
    """Train-only scaler for experimental datasets (research layer only)."""

    feature_order: list[str]
    scaler: StandardScaler | None = None

    def fit(self, X_train: pd.DataFrame) -> ResearchScaler:
        order = [c for c in self.feature_order if c in X_train.columns]
        self.feature_order = order
        self.scaler = StandardScaler()
        self.scaler.fit(X_train.loc[:, order].astype(np.float64).values)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        if self.scaler is None:
            raise RuntimeError("ResearchScaler must be fit before transform")
        return self.scaler.transform(X.loc[:, self.feature_order].astype(np.float64).values)

    def fit_transform_splits(
        self,
        splits: TrainingSplits,
    ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        X_train, y_train = splits.train_xy()
        self.fit(X_train)
        out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for name in ("train", "validation", "test"):
            X, y = splits.feature_matrix(name)
            out[name] = (self.transform(X), y.to_numpy(dtype=int))
        return out


@dataclass
class DatasetVariant:
    variant_id: str
    description: str
    apply_relabel: bool
    event_filter: bool
    feature_selection: bool
    use_tuned_hyperparams: bool


@dataclass
class RetrainRunResult:
    symbol: str
    timeframe: str
    status: str
    report_path: str
    best_model: str
    best_variant: str
    improved_over_baseline: bool
    blocked: bool = False
    block_reason: str = ""
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "report_path": self.report_path,
            "best_model": self.best_model,
            "best_variant": self.best_variant,
            "improved_over_baseline": self.improved_over_baseline,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "summary": self.summary,
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_phase93_findings(base_dir: str | Path | None) -> dict[str, Any]:
    phase93 = _load_json(phase9_3_research_report_path(base_dir))
    importance = _load_json(feature_importance_report_path(base_dir))
    optimization = _load_json(model_optimization_report_path(base_dir))
    top_features = phase93.get("best_features") or [
        r["feature"] for r in importance.get("rankings", [])[:TOP_FEATURE_COUNT]
    ]
    dead = set(importance.get("detection", {}).get("dead_features", [])) | set(DEAD_FEATURES)
    low = set(importance.get("detection", {}).get("low_contribution_features", [])) | set(
        LOW_CONTRIBUTION_FEATURES
    )
    selected = [f for f in top_features if f not in dead and f not in low]
    registry = [f for f in feature_names() if f not in dead and f not in low]
    if len(selected) < 5:
        selected = registry[:TOP_FEATURE_COUNT]
    return {
        "top_features": selected[:TOP_FEATURE_COUNT],
        "dead_features": sorted(dead),
        "excluded_events": sorted(EXCLUDED_EVENT_TYPES),
        "label_config": {
            "atr_period": RESEARCH_ATR_PERIOD,
            "tp_r_multiple": RESEARCH_TP_R,
            "future_window_bars": RESEARCH_FUTURE_WINDOW,
            "sl_r_multiple": 1.0,
        },
        "hyperparameters": {
            m["model"]: m.get("best_params", {})
            for m in optimization.get("models", [])
        },
        "phase9_3_best_model": phase93.get("best_model"),
    }


def _zero_variance_features(df: pd.DataFrame, cols: list[str]) -> list[str]:
    dead: list[str] = []
    for c in cols:
        if c not in df.columns:
            continue
        if df[c].std(skipna=True) <= 1e-12:
            dead.append(c)
    return dead


def _select_features(df: pd.DataFrame, findings: dict[str, Any], *, use_selection: bool) -> list[str]:
    registry = list(feature_names())
    dead = set(findings["dead_features"]) | set(_zero_variance_features(df, registry))
    if use_selection:
        cols = [c for c in findings["top_features"] if c in df.columns and c not in dead]
    else:
        cols = [c for c in registry if c in df.columns and c not in dead]
    if not cols:
        raise ValueError("No features remain after dead-feature removal")
    return cols


def _filter_events(df: pd.DataFrame, *, apply_filter: bool) -> pd.DataFrame:
    if not apply_filter:
        return df
    mask = df["event_type"].isin(HIGH_VALUE_EVENT_TYPES)
    return df.loc[mask].copy()


def build_experimental_dataset(
    source_df: pd.DataFrame,
    candles: pd.DataFrame | None,
    variant: DatasetVariant,
    findings: dict[str, Any],
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Build an isolated experimental dataset variant without touching source v2."""
    work = source_df.copy()
    label_config: dict[str, Any] = {"source": "dataset_v2", "relabel_applied": False}

    if variant.event_filter:
        work = _filter_events(work, apply_filter=True)

    if variant.apply_relabel:
        if candles is None or candles.empty:
            raise ValueError("Candle data required for relabel variant")
        cfg = findings["label_config"]
        work = relabel_dataframe(
            work,
            candles,
            atr_period=int(cfg["atr_period"]),
            tp_r=float(cfg["tp_r_multiple"]),
            future_window_bars=int(cfg["future_window_bars"]),
        )
        label_config = {**cfg, "relabel_applied": True}

    feature_cols = _select_features(work, findings, use_selection=variant.feature_selection)
    work = filter_resolved_labels(work)
    validate_training_splits(work)
    return work, feature_cols, label_config


def splits_from_frame(
    df: pd.DataFrame,
    feature_cols: list[str],
    symbol: str,
    timeframe: str,
) -> TrainingSplits:
    train_df = df.loc[df["split"] == "train"].reset_index(drop=True)
    val_df = df.loc[df["split"] == "validation"].reset_index(drop=True)
    test_df = df.loc[df["split"] == "test"].reset_index(drop=True)
    splits = TrainingSplits(
        train=train_df,
        validation=val_df,
        test=test_df,
        feature_columns=tuple(feature_cols),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
    )
    assert_no_test_leakage(splits)
    return splits


def save_experimental_dataset(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    variant_id: str,
    base_dir: str | Path | None,
) -> Path:
    path = experimental_dataset_path(symbol, timeframe, variant_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def create_research_model(
    name: str,
    seed: int,
    hyperparameters: dict[str, Any] | None = None,
) -> TrainingModel:
    """Research-only model factory with optional tuned hyperparameters."""
    key = name.lower()
    params = hyperparameters or {}

    if key == "logistic":
        est = LogisticRegression(max_iter=500, random_state=seed, solver="lbfgs", n_jobs=1)
        from tradingbot.ml.training.model_factory import _SklearnWrapper

        return _SklearnWrapper("logistic", est)

    if key == "random_forest":
        est = RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 80)),
            max_depth=int(params.get("max_depth", 6)),
            random_state=seed,
            n_jobs=1,
        )
        from tradingbot.ml.training.model_factory import _SklearnWrapper

        return _SklearnWrapper("random_forest", est)

    if key == "xgboost":
        import xgboost as xgb
        from tradingbot.ml.training.model_factory import _SklearnWrapper

        est = xgb.XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=seed,
            n_jobs=1,
            tree_method="hist",
            device="cpu",
            max_depth=int(params.get("max_depth", 4)),
            learning_rate=float(params.get("learning_rate", 0.08)),
            n_estimators=int(params.get("n_estimators", 80)),
            subsample=float(params.get("subsample", 0.9)),
            colsample_bytree=float(params.get("colsample_bytree", 0.9)),
        )
        return _SklearnWrapper("xgboost", est)

    if key == "lightgbm":
        import lightgbm as lgb
        from tradingbot.ml.training.model_factory import _SklearnWrapper

        est = lgb.LGBMClassifier(
            objective="binary",
            random_state=seed,
            n_jobs=1,
            verbosity=-1,
            learning_rate=float(params.get("learning_rate", 0.08)),
            max_depth=int(params.get("max_depth", 4)),
            n_estimators=int(params.get("n_estimators", 80)),
            num_leaves=int(params.get("num_leaves", 31)),
        )
        return _SklearnWrapper("lightgbm", est)

    raise ValueError(f"Unsupported research model: {name}")


def _train_variant_models(
    splits: TrainingSplits,
    variant: DatasetVariant,
    findings: dict[str, Any],
    *,
    seed: int,
) -> list[ModelCandidate]:
    np.random.seed(seed)
    scaler = ResearchScaler(feature_order=list(splits.feature_columns))
    arrays = scaler.fit_transform_splits(splits)
    X_train, y_train = arrays["train"]
    X_val, y_val = arrays["validation"]
    X_test, y_test = arrays["test"]
    eval_sets = (X_val, y_val)
    evaluator = TrainingEvaluator()
    candidates: list[ModelCandidate] = []

    for model_name in RESEARCH_MODELS:
        hp = findings["hyperparameters"].get(model_name, {}) if variant.use_tuned_hyperparams else {}
        model = create_research_model(model_name, seed, hp)
        model.fit(X_train, y_train, eval_set=eval_sets)
        val_m = evaluator.evaluate(model, X_val, y_val, split="validation")
        test_m = evaluator.evaluate(model, X_test, y_test, split="test")
        candidates.append(
            ModelCandidate(
                model_name=model_name,
                variant_id=variant.variant_id,
                validation=val_m,
                test=test_m,
                hyperparameters=hp,
            )
        )
    return candidates


DATASET_VARIANTS: tuple[DatasetVariant, ...] = (
    DatasetVariant(
        variant_id="feature_pruned",
        description="Dead features removed, trading_session excluded, original labels",
        apply_relabel=False,
        event_filter=True,
        feature_selection=True,
        use_tuned_hyperparams=True,
    ),
    DatasetVariant(
        variant_id="research_optimized",
        description="Phase 9.3 label + event filter + feature selection + tuned hyperparams",
        apply_relabel=True,
        event_filter=True,
        feature_selection=True,
        use_tuned_hyperparams=True,
    ),
    DatasetVariant(
        variant_id="tuned_full",
        description="All events, all pruned features, original labels, tuned hyperparams",
        apply_relabel=False,
        event_filter=False,
        feature_selection=False,
        use_tuned_hyperparams=True,
    ),
)


class Phase94RetrainOptimizer:
    """Controlled research retraining based on Phase 9.3 findings."""

    def __init__(self, *, base_dir: str | Path | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed
        self._selector = ModelSelector()

    def run(self, symbol: str, timeframe: str) -> RetrainRunResult:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        store = DatasetStore(self.base_dir)
        source = store.load_v2(symbol, timeframe)
        if source is None or source.empty:
            return self._blocked(symbol, timeframe, "dataset_v2_missing")

        fingerprint_before = dataset_content_fingerprint(source)
        findings = _load_phase93_findings(self.base_dir)
        candles = CandleStore(self.base_dir).load(symbol, timeframe)

        all_candidates: list[ModelCandidate] = []
        variant_meta: dict[str, Any] = {}
        saved_paths: dict[str, str] = {}
        best_features: list[str] = []
        label_config: dict[str, Any] = {}

        research_datasets_root(self.base_dir).mkdir(parents=True, exist_ok=True)

        for variant in DATASET_VARIANTS:
            try:
                if variant.apply_relabel and (candles is None or candles.empty):
                    logger.warning("Skipping variant %s: no candles for relabel", variant.variant_id)
                    continue
                exp_df, features, lbl_cfg = build_experimental_dataset(
                    source,
                    candles,
                    variant,
                    findings,
                )
                if len(exp_df) < 200:
                    logger.warning("Skipping variant %s: insufficient rows (%d)", variant.variant_id, len(exp_df))
                    continue
                path = save_experimental_dataset(exp_df, symbol, timeframe, variant.variant_id, self.base_dir)
                saved_paths[variant.variant_id] = str(path)
                splits = splits_from_frame(exp_df, features, symbol, timeframe)
                candidates = _train_variant_models(splits, variant, findings, seed=self.seed)
                all_candidates.extend(candidates)
                variant_meta[variant.variant_id] = {
                    "description": variant.description,
                    "row_count": len(exp_df),
                    "features": features,
                    "label_config": lbl_cfg,
                    "path": str(path),
                }
                if not best_features:
                    best_features = features
                    label_config = lbl_cfg
            except Exception as exc:
                logger.warning("Variant %s failed: %s", variant.variant_id, exc)

        if not all_candidates:
            return self._blocked(symbol, timeframe, "no_successful_retrain_variants")

        best = self._selector.select_best(all_candidates)
        comparison = self._selector.comparison_table(all_candidates)

        source_after = store.load_v2(symbol, timeframe)
        fingerprint_after = dataset_content_fingerprint(source_after) if source_after is not None else ""

        best_variant_info = variant_meta.get(best.variant_id, {})
        report = build_retraining_report(
            symbol=symbol,
            timeframe=timeframe,
            seed=self.seed,
            dataset_variant={
                "selected": best.variant_id,
                "variants": variant_meta,
            },
            features_used=best_variant_info.get("features", best_features),
            label_config=best_variant_info.get("label_config", label_config),
            candidates=all_candidates,
            best=best,
            comparison_table=comparison,
            experimental_dataset_path=best_variant_info.get("path", ""),
            original_fingerprint=fingerprint_before,
            fingerprint_after=fingerprint_after,
            base_dir=self.base_dir,
        )
        report_path = save_retraining_report(report, self.base_dir)
        improved = bool(report.get("improvement_vs_phase9_2", {}).get("improved_validation_roc_auc"))

        return RetrainRunResult(
            symbol=symbol,
            timeframe=timeframe,
            status=report.get("status", "PASS"),
            report_path=str(report_path),
            best_model=best.model_name,
            best_variant=best.variant_id,
            improved_over_baseline=improved,
            summary={
                "validation_roc_auc": best.validation.classification.get("roc_auc"),
                "test_roc_auc": best.test.classification.get("roc_auc"),
                "improvement_vs_phase9_2": report.get("improvement_vs_phase9_2"),
                "experimental_datasets": saved_paths,
            },
        )

    def _blocked(self, symbol: str, timeframe: str, reason: str) -> RetrainRunResult:
        logger.warning("Phase 9.4 retraining blocked: %s", reason)
        return RetrainRunResult(
            symbol=symbol,
            timeframe=timeframe,
            status="FAIL",
            report_path="",
            best_model="",
            best_variant="",
            improved_over_baseline=False,
            blocked=True,
            block_reason=reason,
        )
