"""Offline research experiment runner — chronological, no shuffle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.models.evaluator import ModelEvaluator
from tradingbot.ml.models.training import create_model
from tradingbot.ml.research.experiment_tracker import ExperimentTracker
from tradingbot.ml.research.reproducibility import build_reproducibility_bundle, dataset_fingerprint, verify_reproducibility
from tradingbot.ml.research.schema import ExperimentRecord, ExperimentStatus, utc_now_iso
from tradingbot.ml.validation._utils import classification_metrics, load_resolved_dataset


@dataclass
class ExperimentConfig:
    model_name: str = "logistic"
    model_version: str = "1.0"
    threshold: float = 0.5
    validation_method: str = "chronological_split"
    feature_subset: list[str] | None = None
    train_split: str = "train"
    test_split: str = "test"
    notes: str = ""


@dataclass
class ResearchExperimentRunner:
    """
    Run offline experiments with chronological validation.

    No random shuffle. No live trading.
    """

    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    base_dir: str | None = None
    tracker: ExperimentTracker | None = None

    def __post_init__(self) -> None:
        self.tracker = self.tracker or ExperimentTracker(self.base_dir)

    def run(self, config: ExperimentConfig | None = None) -> ExperimentRecord:
        cfg = config or ExperimentConfig()
        df, feature_cols = load_resolved_dataset(self.symbol, self.timeframe, self.base_dir)

        if cfg.feature_subset:
            feature_cols = [c for c in cfg.feature_subset if c in feature_cols]

        train = df[df["split"] == cfg.train_split].copy()
        test = df[df["split"] == cfg.test_split].copy()
        if train.empty or test.empty:
            raise ValueError("Train or test split empty — chronological splits required")

        train = train.sort_values("timestamp") if "timestamp" in train.columns else train
        test = test.sort_values("timestamp") if "timestamp" in test.columns else test

        X_train = train[feature_cols]
        y_train = train["label"].astype(int)
        X_test = test[feature_cols]
        y_test = test["label"].astype(int)

        model = create_model(cfg.model_name)
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)
        y_pred = (proba[:, 1] >= cfg.threshold).astype(int)
        metrics = classification_metrics(y_test.values, y_pred, proba)

        evaluator = ModelEvaluator()
        eval_result = evaluator.evaluate(model, X_test, y_test, symbol=self.symbol, timeframe=self.timeframe, split=cfg.test_split)
        expected_r = float(metrics.get("expected_R", eval_result.trading.get("expected_R", 0.0)))

        repro = build_reproducibility_bundle(
            self.symbol,
            self.timeframe,
            model_name=cfg.model_name,
            model_version=cfg.model_version,
            parameters={
                "threshold": cfg.threshold,
                "feature_subset": cfg.feature_subset,
                "train_split": cfg.train_split,
                "test_split": cfg.test_split,
            },
            base_dir=self.base_dir,
        )

        record = ExperimentRecord(
            experiment_id="",
            timestamp=utc_now_iso(),
            dataset_hash=dataset_fingerprint(self.symbol, self.timeframe, self.base_dir),
            feature_version=FEATURE_SCHEMA_VERSION,
            model_name=cfg.model_name,
            model_version=cfg.model_version,
            parameters={
                "threshold": cfg.threshold,
                "feature_count": len(feature_cols),
                "feature_subset": cfg.feature_subset,
                "validation_method": cfg.validation_method,
            },
            validation_method=cfg.validation_method,
            metrics=metrics,
            expected_R=expected_r,
            notes=cfg.notes,
            status=ExperimentStatus.COMPLETE.value,
            symbol=self.symbol,
            timeframe=self.timeframe,
            reproducibility=repro,
        )
        assert self.tracker is not None
        self.tracker.append(record)
        return record

    def compare_configurations(self, configs: list[ExperimentConfig]) -> list[ExperimentRecord]:
        return [self.run(cfg) for cfg in configs]

    def reproduce(self, experiment_id: str) -> dict[str, Any]:
        assert self.tracker is not None
        stored = self.tracker.find_by_id(experiment_id)
        if not stored:
            raise KeyError(f"Experiment not found: {experiment_id}")
        verified = verify_reproducibility(stored, self.symbol, self.timeframe, self.base_dir)
        params = stored.get("parameters", {})
        cfg = ExperimentConfig(
            model_name=stored.get("model_name", "logistic"),
            model_version=stored.get("model_version", "1.0"),
            threshold=float(params.get("threshold", 0.5)),
            feature_subset=params.get("feature_subset"),
            validation_method=stored.get("validation_method", "chronological_split"),
            notes=f"reproduce:{experiment_id}",
        )
        new_record = self.run(cfg)
        return {
            "original_id": experiment_id,
            "new_id": new_record.experiment_id,
            "dataset_verified": verified,
            "expected_R_delta": round(new_record.expected_R - float(stored.get("expected_R", 0.0)), 4),
        }
