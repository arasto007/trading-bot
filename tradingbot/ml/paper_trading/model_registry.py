"""Phase 9.10 — Phase 9.9 frozen model registry for paper trading."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import (
    phase9_9_artifacts_root,
    phase9_9_backup_root,
    phase9_9_config_path,
    phase9_9_feature_order_path,
    phase9_9_freeze_manifest_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.research.regime_optimization.regime_utils import apply_event_filter, assign_market_regime
from tradingbot.ml.research.robustness_optimizer.model_regularization import (
    ModelCandidateConfig,
    create_regularized_model,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.training.data_loader import filter_resolved_labels
from tradingbot.ml.training.model_factory import DEFAULT_SEED, TrainingModel

logger = logging.getLogger(__name__)
PHASE99_ALIAS = "phase9_9_best"
FREEZE_AUTHORITY_RULE = "ACCEPTANCE_PASS_HIGHEST_COMPOSITE"

MODEL_DISPLAY_NAMES: dict[str, str] = {
    "logistic": "LogisticRegression",
    "random_forest": "RandomForestClassifier",
    "xgboost": "XGBClassifier",
    "lightgbm": "LGBMClassifier",
}


class FreezeContractRequiredError(ValueError):
    """Raised when freeze is attempted without a valid FreezeContract."""


@dataclass
class Phase99Bundle:
    model: TrainingModel
    scaler: StandardScaler
    feature_order: list[str]
    config: dict[str, Any]
    metadata: dict[str, Any]

    def transform(self, features: dict[str, float] | pd.Series) -> np.ndarray:
        if isinstance(features, dict):
            frame = pd.DataFrame([{k: features[k] for k in self.feature_order}])
        else:
            frame = pd.DataFrame([features[self.feature_order].astype(np.float64)])
        return self.scaler.transform(frame.values)

    def predict_proba(self, features: dict[str, float] | pd.Series) -> float:
        X = self.transform(features)
        proba = self.model.predict_proba(X)[0]
        return float(proba[1])


@dataclass
class IntegrityResult:
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _training_frame(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    work = filter_resolved_labels(df)
    work = work.copy()
    work["market_regime"] = assign_market_regime(work)
    work = work.loc[work["market_regime"] == config["regime"]]
    return apply_event_filter(work, config.get("event_filter", "A_all_events")).sort_values("timestamp")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    thresholds = dict(contract.get("thresholds") or {})
    model_type = str(contract.get("model_type") or "")
    return {
        "model": MODEL_DISPLAY_NAMES.get(model_type, model_type),
        "parameters": dict(contract.get("hyperparameters") or {}),
        "features": list(contract.get("features") or []),
        "regime": contract.get("regime", "RANGE"),
        "event_filter": contract.get("event_filter", "A_all_events"),
        "risk_pct": float(thresholds.get("risk_pct", 0.005)),
        "buy_threshold": float(thresholds.get("buy_threshold", 0.55)),
        "sell_threshold": float(thresholds.get("sell_threshold", 0.45)),
        "tp_r": float(thresholds.get("tp_r", 2.0)),
        "sl_r": float(thresholds.get("sl_r", 1.0)),
    }


def validate_freeze_contract(contract: dict[str, Any]) -> list[str]:
    from tradingbot.ml.research.robustness_optimizer.model_regularization import build_regularized_candidates

    known_ids = {c.candidate_id for c in build_regularized_candidates()}
    errors: list[str] = []
    required = (
        "candidate_id",
        "model_type",
        "feature_subset",
        "features",
        "hyperparameters",
        "acceptance_status",
    )
    for key in required:
        if not contract.get(key):
            errors.append(f"missing:{key}")
    acceptance = contract.get("acceptance_status") or {}
    if str(acceptance.get("final_verdict", "FAIL")) != "PASS":
        errors.append("acceptance_not_pass")
    checks = acceptance.get("checks") or {}
    if not checks.get("probability_quality_passed"):
        errors.append("probability_gate_not_passed")
    if not checks.get("overfitting_risk_decreased"):
        errors.append("overfitting_check_failed")
    features = contract.get("features") or []
    if not features:
        errors.append("missing_features")
    candidate_id = str(contract.get("candidate_id") or "")
    if candidate_id and candidate_id not in known_ids:
        errors.append("unknown_candidate")
    return errors


def build_test_freeze_contract(
    *,
    candidate_id: str = "logistic_c1",
    model_type: str = "logistic",
    feature_subset: str = "stable_top3",
    features: list[str] | None = None,
    hyperparameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explicit test fixture contract — not a production DEFAULT_CONFIG bypass."""
    feature_list = features or ["ema50_slope", "candle_direction", "structure_distance"]
    return {
        "contract_version": "1.0",
        "phase": "9.9",
        "candidate_id": candidate_id,
        "model_type": model_type,
        "experiment_id": f"{candidate_id}__{feature_subset}__RANGE",
        "feature_subset": feature_subset,
        "features": feature_list,
        "hyperparameters": hyperparameters or {"C": 0.1},
        "thresholds": {
            "buy_threshold": 0.55,
            "sell_threshold": 0.45,
            "tp_r": 2.0,
            "sl_r": 1.0,
            "risk_pct": 0.005,
        },
        "regime": "RANGE",
        "event_filter": "A_all_events",
        "validation_metrics": {
            "robustness_score": 70.0,
            "overfitting_risk": "HIGH",
            "mean_profit_factor": 1.2,
            "mean_expectancy": 0.1,
            "mean_auc_gap": 0.05,
            "profitable_windows": 4,
            "window_count": 5,
            "composite_score": 0.6,
        },
        "probability_metrics": {
            "buy_coverage_pct": 10.0,
            "sell_coverage_pct": 70.0,
            "probability_std": 0.1,
            "min_probability": 0.1,
            "max_probability": 0.9,
            "probability_gate_passed": True,
        },
        "acceptance_status": {
            "final_verdict": "PASS",
            "checks": {
                "robustness_improved": True,
                "overfitting_risk_decreased": True,
                "mean_expectancy_positive": True,
                "profitable_windows_ge_4": True,
                "probability_quality_passed": True,
            },
            "overfitting_check_mode": "numeric_mean_auc_gap",
        },
        "metadata": {
            "artifact_write": True,
            "bridge_mode": "test_fixture",
        },
    }


def _backup_existing_artifacts(base_dir: str | Path | None) -> str | None:
    root = phase9_9_artifacts_root(base_dir)
    if not phase9_9_model_path(base_dir).is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = phase9_9_backup_root(base_dir) / stamp
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, backup_dir, dirs_exist_ok=True)
    logger.info("Backed up Phase 9.9 artifacts to %s", backup_dir)
    return str(backup_dir)


def _previous_candidate_snapshot(base_dir: str | Path | None) -> dict[str, Any] | None:
    meta_path = phase9_9_metadata_path(base_dir)
    if not meta_path.is_file():
        return None
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    return {
        "candidate_id": metadata.get("candidate_id"),
        "experiment_id": metadata.get("experiment_id"),
        "feature_subset": metadata.get("feature_subset"),
        "model_type": metadata.get("model_type"),
        "frozen_at_utc": metadata.get("frozen_at_utc"),
    }


def _write_freeze_manifest(
    *,
    base_dir: str | Path | None,
    contract: dict[str, Any],
    backup_path: str | None,
    report_path: str | None,
) -> dict[str, Any]:
    artifact_paths = {
        "model.pkl": phase9_9_model_path(base_dir),
        "scaler.pkl": phase9_9_scaler_path(base_dir),
        "feature_order.json": phase9_9_feature_order_path(base_dir),
        "config.json": phase9_9_config_path(base_dir),
        "metadata.json": phase9_9_metadata_path(base_dir),
    }
    checksums = {
        name: _sha256_file(path) for name, path in artifact_paths.items() if path.is_file()
    }
    manifest = {
        "manifest_version": "1.0",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_authority": FREEZE_AUTHORITY_RULE,
        "previous_candidate": _previous_candidate_snapshot(base_dir),
        "new_candidate": {
            "candidate_id": contract.get("candidate_id"),
            "experiment_id": contract.get("experiment_id"),
            "model_type": contract.get("model_type"),
            "feature_subset": contract.get("feature_subset"),
        },
        "acceptance_snapshot": contract.get("acceptance_status"),
        "dataset_fingerprint": (contract.get("metadata") or {}).get("dataset_fingerprint"),
        "report_path": report_path,
        "backup_path": backup_path,
        "artifact_checksums": checksums,
    }
    manifest_path = phase9_9_freeze_manifest_path(base_dir)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def freeze_phase9_9_from_contract(
    df: pd.DataFrame,
    contract: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
    seed: int = DEFAULT_SEED,
    report_path: str | None = None,
) -> Phase99Bundle:
    """Train and persist frozen Phase 9.9 artifacts from an acceptance-gated FreezeContract."""
    errors = validate_freeze_contract(contract)
    if errors:
        raise FreezeContractRequiredError("; ".join(errors))

    cfg = _config_from_contract(contract)
    features = list(cfg["features"])
    frame = _training_frame(df, cfg)
    if len(frame) < 50:
        raise ValueError("Insufficient RANGE rows to freeze Phase 9.9 artifacts")

    backup_path = _backup_existing_artifacts(base_dir)

    n = len(frame)
    cut = int(n * 0.85)
    train = frame.iloc[:cut]

    scaler = StandardScaler()
    X_tr = train.loc[:, features].astype(np.float64).values
    y_tr = train["label"].astype(int).to_numpy()
    scaler.fit(X_tr)

    candidate = ModelCandidateConfig(
        candidate_id=str(contract["candidate_id"]),
        model_name=str(contract["model_type"]),
        hyperparameters=dict(contract.get("hyperparameters") or {}),
    )
    model = create_regularized_model(candidate, seed)
    model.fit(scaler.transform(X_tr), y_tr)

    root = phase9_9_artifacts_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, phase9_9_model_path(base_dir))
    joblib.dump(scaler, phase9_9_scaler_path(base_dir))
    phase9_9_feature_order_path(base_dir).write_text(
        json.dumps({"feature_order": features}, indent=2),
        encoding="utf-8",
    )
    phase9_9_config_path(base_dir).write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    validation_metrics = contract.get("validation_metrics") or {}
    metadata = {
        "phase": "9.9",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": contract["candidate_id"],
        "experiment_id": contract.get("experiment_id"),
        "feature_subset": contract.get("feature_subset"),
        "model_type": contract.get("model_type"),
        "train_rows": len(train),
        "dataset_fingerprint": dataset_content_fingerprint(df),
        "robustness_score": validation_metrics.get("robustness_score"),
        "validation_metrics": validation_metrics,
        "probability_metrics": contract.get("probability_metrics"),
        "acceptance_status": contract.get("acceptance_status"),
        "freeze_authority": FREEZE_AUTHORITY_RULE,
        "contract_version": contract.get("contract_version", "1.0"),
    }
    phase9_9_metadata_path(base_dir).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    contract_with_fp = {
        **contract,
        "metadata": {
            **(contract.get("metadata") or {}),
            "dataset_fingerprint": metadata["dataset_fingerprint"],
            "artifact_write": True,
        },
    }
    _write_freeze_manifest(
        base_dir=base_dir,
        contract=contract_with_fp,
        backup_path=backup_path,
        report_path=report_path,
    )
    logger.info(
        "Frozen Phase 9.9 artifacts for %s at %s",
        contract.get("experiment_id"),
        root,
    )
    return Phase99Bundle(model=model, scaler=scaler, feature_order=features, config=cfg, metadata=metadata)


def freeze_phase9_9_artifacts(
    df: pd.DataFrame,
    *,
    contract: dict[str, Any],
    base_dir: str | Path | None = None,
    seed: int = DEFAULT_SEED,
    report_path: str | None = None,
    config: dict[str, Any] | None = None,
) -> Phase99Bundle:
    """Freeze Phase 9.9 artifacts — requires acceptance-gated FreezeContract."""
    if contract is None:
        raise FreezeContractRequiredError(
            "FreezeContract required; DEFAULT_CONFIG / hardcoded candidate freeze removed in Phase 22AJ"
        )
    if config is not None:
        logger.warning("config= argument ignored; freeze uses FreezeContract fields only")
    return freeze_phase9_9_from_contract(
        df,
        contract,
        base_dir=base_dir,
        seed=seed,
        report_path=report_path,
    )


def load_phase9_9_bundle(
    *,
    base_dir: str | Path | None = None,
    build_if_missing: bool = False,
    training_df: pd.DataFrame | None = None,
    seed: int = DEFAULT_SEED,
    contract: dict[str, Any] | None = None,
) -> Phase99Bundle:
    model_path = phase9_9_model_path(base_dir)
    if not model_path.is_file():
        if build_if_missing:
            if training_df is None or contract is None:
                raise FileNotFoundError(
                    "Phase 9.9 artifacts missing; silent rebuild blocked. "
                    "Provide training_df and FreezeContract, or run optimizer with acceptance PASS."
                )
            return freeze_phase9_9_artifacts(
                training_df,
                contract=contract,
                base_dir=base_dir,
                seed=seed,
            )
        raise FileNotFoundError(f"Phase 9.9 model not found: {model_path}")

    model = joblib.load(model_path)
    scaler = joblib.load(phase9_9_scaler_path(base_dir))
    order_payload = json.loads(phase9_9_feature_order_path(base_dir).read_text(encoding="utf-8"))
    feature_order = list(order_payload.get("feature_order") or order_payload.get("features") or [])
    config = json.loads(phase9_9_config_path(base_dir).read_text(encoding="utf-8"))
    meta_path = phase9_9_metadata_path(base_dir)
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return Phase99Bundle(
        model=model,
        scaler=scaler,
        feature_order=feature_order,
        config=config,
        metadata=metadata,
    )


def verify_bundle_integrity(bundle: Phase99Bundle, features: dict[str, float]) -> IntegrityResult:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    missing = [f for f in bundle.feature_order if f not in features]
    checks["feature_order"] = len(missing) == 0
    if missing:
        errors.append(f"missing features: {missing}")
    n_in = getattr(bundle.scaler, "n_features_in_", len(bundle.feature_order))
    checks["scaler_dims"] = int(n_in) == len(bundle.feature_order)
    try:
        p = bundle.predict_proba(features)
        checks["predict"] = 0.0 <= p <= 1.0
    except Exception as exc:
        checks["predict"] = False
        errors.append(str(exc))
    status = "PASS" if all(checks.values()) else "FAIL"
    return IntegrityResult(status=status, checks=checks, errors=errors)
