"""Phase 9.7 — load and validate Phase 9.6 research model artifacts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import (
    phase9_6_artifacts_root,
    phase9_6_feature_order_path,
    phase9_6_model_metadata_path,
    phase9_6_model_path,
    phase9_6_optimization_report_path,
    phase9_6_scaler_path,
    regime_optimization_dataset_path,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.training.model_factory import DEFAULT_SEED, TrainingModel

logger = logging.getLogger(__name__)
PHASE96_MODEL_ALIAS = "phase9_6_best"


@dataclass
class IntegrityResult:
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


@dataclass
class Phase96ModelBundle:
    model: TrainingModel
    scaler: StandardScaler
    feature_order: list[str]
    metadata: dict[str, Any]
    configuration: dict[str, Any]
    dataset_fingerprint: str

    def transform_row(self, row: pd.Series) -> np.ndarray:
        frame = pd.DataFrame([row[self.feature_order].astype(np.float64)])
        return self.scaler.transform(frame.values)


def load_phase9_6_report(base_dir: str | Path | None = None) -> dict[str, Any]:
    path = phase9_6_optimization_report_path(base_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Phase 9.6 report not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _feature_list_from_report(report: dict[str, Any]) -> list[str]:
    sets = report.get("feature_findings", {}).get("feature_sets", {})
    best_set = report.get("best_configuration", {}).get("feature_set", "A_top10_stable")
    features = sets.get(best_set) or sets.get("A_top10_stable") or []
    if not features:
        features = report.get("feature_findings", {}).get("stable_features", [])
    return list(features)


def _load_training_frame(symbol: str, timeframe: str, report: dict[str, Any], base_dir: str | Path | None) -> pd.DataFrame:
    config_id = report.get("model_optimization", {}).get("best_candidate", {}).get("variant_id")
    if not config_id:
        regime = report["best_configuration"]["regime"]
        scheme = report["best_configuration"]["event_filter"]
        feature_set = report["best_configuration"]["feature_set"]
        config_id = f"{regime}__{scheme}__{feature_set}"
    path = regime_optimization_dataset_path(symbol, timeframe, config_id, base_dir)
    if path.is_file():
        return pd.read_parquet(path)
    saved = report.get("model_optimization", {}).get("saved_datasets", {})
    if config_id in saved:
        alt = Path(saved[config_id])
        if alt.is_file():
            return pd.read_parquet(alt)
    raise FileNotFoundError(f"Phase 9.6 training dataset not found for {config_id}")


def build_phase9_6_artifacts(
    symbol: str,
    timeframe: str,
    *,
    base_dir: str | Path | None = None,
    seed: int = DEFAULT_SEED,
) -> Phase96ModelBundle:
    """Train and persist isolated Phase 9.6 best model (research path only)."""
    report = load_phase9_6_report(base_dir)
    features = _feature_list_from_report(report)
    if not features:
        raise ValueError("Phase 9.6 report has no feature list")

    frame = _load_training_frame(symbol, timeframe, report, base_dir)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    n = len(frame)
    cut1 = int(n * 0.7)
    cut2 = int(n * 0.85)
    train = frame.iloc[:cut1]
    val = frame.iloc[cut1:cut2]

    cols = [c for c in features if c in train.columns]
    if not cols:
        raise ValueError("No Phase 9.6 features present in training frame")

    scaler = StandardScaler()
    X_tr = train.loc[:, cols].astype(np.float64).values
    y_tr = train["label"].astype(int).to_numpy()
    scaler.fit(X_tr)
    X_va = scaler.transform(val.loc[:, cols].astype(np.float64).values)
    y_va = val["label"].astype(int).to_numpy()

    model_name = report.get("best_configuration", {}).get("model", "xgboost")
    hp = report.get("model_optimization", {}).get("best_candidate", {}).get("hyperparameters", {})
    model = create_research_model(model_name, seed, hp)
    model.fit(scaler.transform(X_tr), y_tr, eval_set=(X_va, y_va))

    root = phase9_6_artifacts_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, phase9_6_model_path(base_dir))
    joblib.dump(scaler, phase9_6_scaler_path(base_dir))
    phase9_6_feature_order_path(base_dir).write_text(
        json.dumps({"feature_order": cols}, indent=2),
        encoding="utf-8",
    )
    metadata = {
        "phase": "9.6",
        "model_name": model_name,
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "configuration": report.get("best_configuration", {}),
        "hyperparameters": hp,
        "feature_count": len(cols),
        "train_rows": len(train),
        "validation_rows": len(val),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_fingerprint": report.get("dataset", {}).get("fingerprint", ""),
    }
    phase9_6_model_metadata_path(base_dir).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Built Phase 9.6 artifacts at %s", root)
    return load_phase9_6_bundle(base_dir=base_dir, build_if_missing=False)


def load_phase9_6_bundle(
    *,
    base_dir: str | Path | None = None,
    build_if_missing: bool = True,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = DEFAULT_SEED,
) -> Phase96ModelBundle:
    model_path = phase9_6_model_path(base_dir)
    if not model_path.is_file() and build_if_missing:
        return build_phase9_6_artifacts(symbol, timeframe, base_dir=base_dir, seed=seed)

    if not model_path.is_file():
        raise FileNotFoundError(f"Phase 9.6 model artifact missing: {model_path}")

    model = joblib.load(model_path)
    scaler = joblib.load(phase9_6_scaler_path(base_dir))
    order_payload = json.loads(phase9_6_feature_order_path(base_dir).read_text(encoding="utf-8"))
    feature_order = list(order_payload.get("feature_order") or order_payload.get("features") or [])
    metadata_path = phase9_6_model_metadata_path(base_dir)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    report = load_phase9_6_report(base_dir)
    return Phase96ModelBundle(
        model=model,
        scaler=scaler,
        feature_order=feature_order,
        metadata=metadata,
        configuration=report.get("best_configuration", {}),
        dataset_fingerprint=str(report.get("dataset", {}).get("fingerprint", "")),
    )


def verify_integrity(
    bundle: Phase96ModelBundle,
    dataset_df: pd.DataFrame,
    *,
    expected_fingerprint: str | None = None,
) -> IntegrityResult:
    """Validate dataset fingerprint, feature schema, and scaler/model compatibility."""
    checks: dict[str, bool] = {}
    errors: list[str] = []

    fp = dataset_content_fingerprint(dataset_df)
    expected = expected_fingerprint or bundle.dataset_fingerprint
    checks["dataset_fingerprint"] = not expected or fp == expected
    if expected and fp != expected:
        errors.append("dataset fingerprint mismatch")

    missing = [c for c in bundle.feature_order if c not in dataset_df.columns]
    checks["feature_schema"] = len(missing) == 0
    if missing:
        errors.append(f"missing features: {missing}")

    n_in = getattr(bundle.scaler, "n_features_in_", len(bundle.feature_order))
    checks["scaler_feature_count"] = int(n_in) == len(bundle.feature_order)
    if int(n_in) != len(bundle.feature_order):
        errors.append("scaler feature count mismatch")

    try:
        sample = dataset_df.iloc[:1]
        X = bundle.transform_row(sample.iloc[0])
        proba = bundle.model.predict_proba(X)
        checks["model_predict"] = proba.shape[0] == 1
    except Exception as exc:
        checks["model_predict"] = False
        errors.append(f"model predict failed: {exc}")

    status = "PASS" if all(checks.values()) else "FAIL"
    return IntegrityResult(status=status, checks=checks, errors=errors)


def resolve_model_arg(model_arg: str) -> str:
    if model_arg in (PHASE96_MODEL_ALIAS, "phase9_6", "phase9.6"):
        return PHASE96_MODEL_ALIAS
    return model_arg
