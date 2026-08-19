"""Phase 9.2 — production ML training on audited dataset v2 (offline, CPU-only)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from tradingbot.ml.data.paths import (
    production_best_model_path,
    production_feature_order_path,
    production_model_metadata_path,
    production_scaler_path,
    training_comparison_report_path,
    training_models_root,
)
from tradingbot.ml.dataset.deep_audit import deep_audit_report_path
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.training.data_loader import (
    assert_no_test_leakage,
    load_dataset_v2_splits,
    resolve_feature_columns,
)
from tradingbot.ml.training.evaluation import TrainingEvaluator
from tradingbot.ml.training.feature_pipeline import FeaturePipeline
from tradingbot.ml.training.model_factory import (
    DEFAULT_SEED,
    TrainingModel,
    create_training_model,
)
from tradingbot.ml.training.model_registry import (
    ModelBundle,
    next_version,
    save_model_bundle,
)
from tradingbot.ml.training.trainer import TrainingRunResult

logger = logging.getLogger(__name__)

PHASE = "9.2"
PHASE9_MODELS = ("logistic", "random_forest", "xgboost", "lightgbm")
SELECTION_METRIC = "validation_roc_auc"


@dataclass
class PreTrainingSanity:
    passed: bool
    checks: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": self.checks, "issues": self.issues}


def resolve_phase9_model_list() -> list[str]:
    """All four baseline models are required for Phase 9.2."""
    models = list(PHASE9_MODELS)
    try:
        import xgboost  # noqa: F401
    except ImportError as exc:
        raise ImportError("Phase 9.2 requires xgboost") from exc
    try:
        import lightgbm  # noqa: F401
    except ImportError as exc:
        raise ImportError("Phase 9.2 requires lightgbm") from exc
    return models


def load_deep_audit_status(base_dir: str | Path | None) -> dict[str, Any]:
    path = deep_audit_report_path(base_dir)
    if not path.is_file():
        return {"found": False, "status": "missing", "path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "found": True,
        "status": str(payload.get("status", "unknown")).lower(),
        "health_score": payload.get("health_score"),
        "path": str(path),
        "phase": payload.get("phase"),
    }


def run_pre_training_sanity(
    df,
    symbol: str,
    timeframe: str,
    base_dir: str | Path | None,
    *,
    min_samples: int = 500,
) -> PreTrainingSanity:
    """Final checks before fitting — deep audit pass, leakage, features, splits."""
    issues: list[str] = []
    checks: dict[str, Any] = {}

    audit = load_deep_audit_status(base_dir)
    checks["deep_audit"] = audit
    if not audit["found"]:
        issues.append("deep_audit_report_missing")
    elif audit["status"] != "pass":
        issues.append(f"deep_audit_not_pass:{audit['status']}")

    sanity = DatasetSanityGate(min_samples=min_samples).evaluate(df, symbol, timeframe)
    checks["sanity_gate"] = sanity.to_dict()
    if sanity.blocked:
        issues.append(f"sanity_gate_blocked:{sanity.status}")

    leakage = DatasetLeakageAuditor().audit(df, symbol, timeframe)
    checks["leakage"] = {"status": leakage.status}
    if leakage.status == "fail":
        issues.append("leakage_audit_failed")

    expected_features = list(feature_names())
    cols = resolve_feature_columns(df)
    checks["feature_columns"] = {
        "expected_count": len(expected_features),
        "actual_count": len(cols),
        "match_registry": cols == expected_features,
    }
    if cols != expected_features:
        issues.append("feature_order_mismatch")

    try:
        splits = load_dataset_v2_splits(symbol, timeframe, base_dir)
        assert_no_test_leakage(splits)
        checks["splits"] = {
            "train": len(splits.train),
            "validation": len(splits.validation),
            "test": len(splits.test),
            "temporal_leakage": False,
        }
    except Exception as exc:
        issues.append(f"split_validation_failed:{exc}")
        checks["splits"] = {"error": str(exc)}

    return PreTrainingSanity(passed=len(issues) == 0, checks=checks, issues=issues)


def save_production_artifacts(
    bundle: ModelBundle,
    *,
    comparison_report: dict[str, Any],
    base_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Write canonical Phase 9.2 artifacts under data/ml/models/ and comparison report."""
    root = training_models_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)

    model_path = production_best_model_path(base_dir)
    scaler_path = production_scaler_path(base_dir)
    order_path = production_feature_order_path(base_dir)
    meta_path = production_model_metadata_path(base_dir)
    report_path = training_comparison_report_path(base_dir)

    bundle.model.save(model_path)
    if bundle.feature_pipeline.scaler is None:
        raise RuntimeError("Feature pipeline scaler is not fitted")
    joblib.dump(bundle.feature_pipeline.scaler, scaler_path)
    order_path.write_text(
        json.dumps({"feature_order": bundle.feature_pipeline.feature_order}, indent=2),
        encoding="utf-8",
    )

    metadata = {
        **bundle.metadata,
        "phase": PHASE,
        "version": bundle.version,
        "model_name": bundle.model.name,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "best_model": str(model_path),
            "scaler": str(scaler_path),
            "feature_order": str(order_path),
            "metadata": str(meta_path),
        },
        "selection_metric": SELECTION_METRIC,
    }
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(comparison_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {
        "best_model": model_path,
        "scaler": scaler_path,
        "feature_order": order_path,
        "model_metadata": meta_path,
        "training_comparison_report": report_path,
    }


def load_production_bundle(base_dir: str | Path | None = None) -> tuple[TrainingModel, FeaturePipeline, dict[str, Any]]:
    """Load canonical Phase 9.2 best model, scaler, and metadata."""
    meta_path = production_model_metadata_path(base_dir)
    if not meta_path.is_file():
        raise FileNotFoundError(f"Production metadata not found: {meta_path}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    model = TrainingModel.load(production_best_model_path(base_dir))
    scaler = joblib.load(production_scaler_path(base_dir))
    order_payload = json.loads(production_feature_order_path(base_dir).read_text(encoding="utf-8"))
    order = order_payload.get("feature_order") or order_payload.get("features")
    pipeline = FeaturePipeline(feature_order=list(order), scaler=scaler)
    return model, pipeline, metadata


class Phase92ProductionTrainer:
    """
    Phase 9.2 training orchestrator.

    Gates on Phase 9.1.5 deep audit PASS (not train-readiness).
    Scaler fit on train only; model selection on validation ROC-AUC.
    """

    def __init__(
        self,
        *,
        base_dir: str | None = None,
        seed: int = DEFAULT_SEED,
        min_samples: int = 500,
    ) -> None:
        self.base_dir = base_dir
        self.seed = seed
        self.min_samples = min_samples
        self._evaluator = TrainingEvaluator()

    def run(
        self,
        symbol: str,
        timeframe: str,
        *,
        version: str | None = None,
    ) -> TrainingRunResult:
        np.random.seed(self.seed)
        models = resolve_phase9_model_list()
        ver = version or next_version(self.base_dir)

        raw_df = DatasetStore(self.base_dir).load_v2(symbol, timeframe)
        if raw_df is None or raw_df.empty:
            return self._blocked(ver, symbol, timeframe, models, "dataset_v2_missing")

        sanity = run_pre_training_sanity(
            raw_df,
            symbol,
            timeframe,
            self.base_dir,
            min_samples=self.min_samples,
        )
        if not sanity.passed:
            reason = "pre_training_sanity_failed:" + ";".join(sanity.issues)
            return self._blocked(ver, symbol, timeframe, models, reason)

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
            m = create_training_model(model_name, seed=self.seed)
            m.fit(X_train_s, y_train_np, eval_set=eval_sets)
            trained[model_name] = m
            val_metrics = self._evaluator.evaluate(m, X_val_s, y_val_np, split="validation")
            test_metrics = self._evaluator.evaluate(m, X_test_s, y_test_np, split="test")
            evaluations[model_name] = {
                "validation": val_metrics.to_dict(),
                "test": test_metrics.to_dict(),
            }

        best = self._select_best_model(models, evaluations)
        bundle = ModelBundle(
            version=ver,
            model=trained[best],
            feature_pipeline=pipeline,
            metadata={
                "phase": PHASE,
                "symbol": symbol.upper(),
                "timeframe": timeframe.upper(),
                "seed": self.seed,
                "model_name": best,
                "all_models": models,
                "feature_pipeline": pipeline.metadata(),
                "pre_training_sanity": sanity.to_dict(),
                "row_counts": {
                    "train": len(splits.train),
                    "validation": len(splits.validation),
                    "test": len(splits.test),
                },
            },
        )
        versioned_paths = save_model_bundle(bundle, base_dir=self.base_dir)

        comparison_report = {
            "phase": PHASE,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "seed": self.seed,
            "dataset": "v2",
            "models_trained": models,
            "best_model": best,
            "selection_criteria": SELECTION_METRIC,
            "selection_scores": {
                name: evaluations[name]["validation"]["classification"].get("roc_auc", 0.0)
                for name in models
            },
            "evaluations": evaluations,
            "pre_training_sanity": sanity.to_dict(),
            "row_counts": bundle.metadata["row_counts"],
            "versioned_artifacts": {k: str(v) for k, v in versioned_paths.items()},
        }
        production_paths = save_production_artifacts(
            bundle,
            comparison_report=comparison_report,
            base_dir=self.base_dir,
        )

        artifacts = {k: str(v) for k, v in production_paths.items()}
        artifacts.update({f"versioned_{k}": str(v) for k, v in versioned_paths.items()})

        return TrainingRunResult(
            version=ver,
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            seed=self.seed,
            models=models,
            primary_model=best,
            evaluations=evaluations,
            artifacts=artifacts,
            report_path=str(production_paths["training_comparison_report"]),
        )

    @staticmethod
    def _select_best_model(models: list[str], evaluations: dict[str, dict[str, Any]]) -> str:
        priority = ["xgboost", "lightgbm", "random_forest", "logistic"]

        def score(name: str) -> float:
            val = evaluations.get(name, {}).get("validation", {})
            cls = val.get("classification", {})
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
        logger.warning("Phase 9.2 training blocked: %s", reason)
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
