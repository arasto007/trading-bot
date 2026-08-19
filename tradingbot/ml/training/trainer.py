"""Production training orchestrator for Phase 8.6."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.train_readiness_report import TrainReadinessAnalyzer
from tradingbot.ml.training.data_loader import (
    TrainingSplits,
    assert_no_test_leakage,
    load_dataset_v2_splits,
)
from tradingbot.ml.training.evaluation import EvaluationMetrics, TrainingEvaluator
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import (
    DEFAULT_SEED,
    TrainingModel,
    create_training_model,
    resolve_model_list,
)
from tradingbot.ml.training.model_registry import (
    ModelBundle,
    next_version,
    save_model_bundle,
    save_training_report,
)
from tradingbot.ml.training.train_state import TrainState, TrainStateStore

logger = logging.getLogger(__name__)


@dataclass
class TrainingRunResult:
    version: str
    symbol: str
    timeframe: str
    seed: int
    models: list[str]
    primary_model: str
    evaluations: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    report_path: str = ""
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "seed": self.seed,
            "models": self.models,
            "primary_model": self.primary_model,
            "evaluations": self.evaluations,
            "artifacts": self.artifacts,
            "report_path": self.report_path,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


class ProductionTrainer:
    """
    Deterministic offline training pipeline on dataset v2.

    Flow: load v2 -> sanity gate -> readiness -> feature pipeline ->
    split validation -> train models -> evaluate -> registry save -> report.
    """

    def __init__(
        self,
        *,
        base_dir: str | None = None,
        seed: int = DEFAULT_SEED,
        min_samples: int = 500,
        resume: bool = False,
    ) -> None:
        self.base_dir = base_dir
        self.seed = seed
        self.min_samples = min_samples
        self.resume = resume
        self._evaluator = TrainingEvaluator()
        self._state_store = TrainStateStore(base_dir)

    def run(
        self,
        symbol: str,
        timeframe: str,
        model: str = "all",
        *,
        version: str | None = None,
    ) -> TrainingRunResult:
        np.random.seed(self.seed)
        models = resolve_model_list(model)
        ver = version or next_version(self.base_dir)

        state = TrainState(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            version=ver,
            seed=self.seed,
            models_pending=list(models),
            models_completed=[],
            status="in_progress",
        )
        if self.resume:
            existing = self._state_store.load()
            if existing and existing.status == "in_progress" and existing.version == ver:
                state = existing
                models = list(state.models_pending) or models

        self._state_store.save(state)

        try:
            raw_df = DatasetStore(self.base_dir).load_v2(symbol, timeframe)
            if raw_df is None or raw_df.empty:
                return self._blocked(ver, symbol, timeframe, models, "dataset_v2_missing")

            sanity = DatasetSanityGate(min_samples=self.min_samples).evaluate(raw_df, symbol, timeframe)
            if sanity.blocked:
                return self._blocked(
                    ver,
                    symbol,
                    timeframe,
                    models,
                    f"sanity_gate_blocked:{sanity.status}",
                )

            readiness = TrainReadinessAnalyzer(min_samples=self.min_samples).analyze(raw_df, symbol, timeframe)
            if not readiness.recommended_for_training:
                return self._blocked(ver, symbol, timeframe, models, "train_readiness_blocked")

            leakage = DatasetLeakageAuditor().audit(raw_df, symbol, timeframe)
            if leakage.status == "fail":
                return self._blocked(ver, symbol, timeframe, models, "leakage_audit_blocked")

            splits = load_dataset_v2_splits(symbol, timeframe, self.base_dir)
            assert_no_test_leakage(splits)

            X_train, y_train = splits.train_xy()
            X_val, y_val = splits.validation_xy()
            X_test, y_test = splits.test_xy()

            pipeline = FeaturePipeline.from_registry()
            X_train_s, X_val_s, X_test_s = pipeline.fit_transform_train(X_train, X_val, X_test)

            y_train_np = y_train.to_numpy(dtype=int)
            y_val_np = y_val.to_numpy(dtype=int)
            y_test_np = y_test.to_numpy(dtype=int)

            evaluations: dict[str, dict[str, Any]] = {}
            trained: dict[str, TrainingModel] = {}
            eval_sets = (X_val_s, y_val_np)

            for model_name in models:
                if self.resume and model_name in state.models_completed:
                    continue
                m = create_training_model(model_name, seed=self.seed)
                m.fit(X_train_s, y_train_np, eval_set=eval_sets)
                trained[model_name] = m
                val_metrics = self._evaluator.evaluate(m, X_val_s, y_val_np, split="validation")
                test_metrics = self._evaluator.evaluate(m, X_test_s, y_test_np, split="test")
                evaluations[model_name] = {
                    "validation": val_metrics.to_dict(),
                    "test": test_metrics.to_dict(),
                }
                self._state_store.mark_model_complete(state, model_name)

            primary = self._select_primary_model(models, evaluations)
            bundle = ModelBundle(
                version=ver,
                model=trained[primary],
                feature_pipeline=pipeline,
                metadata={
                    "symbol": symbol.upper(),
                    "timeframe": timeframe.upper(),
                    "seed": self.seed,
                    "model_name": primary,
                    "all_models": models,
                    "feature_pipeline": pipeline.metadata(),
                    "sanity_status": sanity.status,
                    "readiness_status": readiness.recommended_for_training,
                },
            )
            paths = save_model_bundle(bundle, base_dir=self.base_dir)

            report = {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "version": ver,
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "seed": self.seed,
                "primary_model": primary,
                "models_trained": models,
                "row_counts": {
                    "train": len(splits.train),
                    "validation": len(splits.validation),
                    "test": len(splits.test),
                },
                "evaluations": evaluations,
                "artifacts": {k: str(v) for k, v in paths.items()},
                "gates": {
                    "sanity": sanity.to_dict(),
                    "readiness": readiness.to_dict(),
                    "leakage_status": leakage.status,
                },
            }
            report_path = save_training_report(report, ver, self.base_dir)
            self._state_store.clear()

            return TrainingRunResult(
                version=ver,
                symbol=symbol.upper(),
                timeframe=timeframe.upper(),
                seed=self.seed,
                models=models,
                primary_model=primary,
                evaluations=evaluations,
                artifacts={k: str(v) for k, v in paths.items()},
                report_path=str(report_path),
            )
        except Exception as exc:
            self._state_store.mark_failed(state, str(exc))
            raise

    def evaluate_existing(
        self,
        model_path: str,
        symbol: str,
        timeframe: str,
    ) -> dict[str, Any]:
        from tradingbot.ml.training.model_registry import resolve_model_path

        path = resolve_model_path(model_path, self.base_dir)
        model = TrainingModel.load(path)
        splits = load_dataset_v2_splits(symbol, timeframe, self.base_dir)
        assert_no_test_leakage(splits)

        ver = path.stem.replace("model_v", "")
        pipeline = FeaturePipeline.load(ver, self.base_dir)

        results: dict[str, Any] = {"model": model.name, "version": ver, "splits": {}}
        for split_name in ("validation", "test"):
            X, y = splits.feature_matrix(split_name)
            X_s = pipeline.transform(X)
            metrics = self._evaluator.evaluate(model, X_s, y.to_numpy(), split=split_name)
            results["splits"][split_name] = metrics.to_dict()
        return results

    @staticmethod
    def _select_primary_model(models: list[str], evaluations: dict[str, dict[str, Any]]) -> str:
        priority = ["xgboost", "lightgbm", "random_forest", "logistic"]

        def score(name: str) -> float:
            test = evaluations.get(name, {}).get("test", {})
            cls = test.get("classification", {})
            return float(cls.get("roc_auc", 0.0))

        ranked = sorted(models, key=lambda n: (-score(n), priority.index(n) if n in priority else 99))
        return ranked[0]

    def _blocked(
        self,
        version: str,
        symbol: str,
        timeframe: str,
        models: list[str],
        reason: str,
    ) -> TrainingRunResult:
        logger.warning("Training blocked: %s", reason)
        return TrainingRunResult(
            version=version,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            seed=self.seed,
            models=models,
            primary_model=models[0] if models else "",
            blocked=True,
            block_reason=reason,
        )
