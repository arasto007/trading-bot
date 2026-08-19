"""Phase 22AK — controlled end-to-end freeze execution validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_8_robustness_report_path,
    phase9_8_window_results_path,
    phase9_9_artifacts_root,
    phase9_9_backup_root,
    phase9_9_config_path,
    phase9_9_feature_order_path,
    phase9_9_freeze_manifest_path,
    phase9_9_metadata_path,
    phase9_9_model_comparison_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.paper_trading.model_registry import (
    load_phase9_9_bundle,
    validate_freeze_contract,
    verify_bundle_integrity,
)
from tradingbot.ml.phase15a.config import EXPECTED_DATASET_FINGERPRINT
from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric
from tradingbot.ml.research.robustness_optimizer.candidate_selector import (
    PRODUCTION_WINNER_RULE,
    select_best,
    select_production_winner,
)
from tradingbot.ml.research.robustness_optimizer.freeze_bridge import (
    VALIDATION_METRIC_KEYS,
    PROBABILITY_METRIC_KEYS,
    validate_accepted_candidate,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

ARTIFACT_FILES = (
    "model.pkl",
    "scaler.pkl",
    "feature_order.json",
    "config.json",
    "metadata.json",
    "freeze_manifest.json",
)

EXPECTED_SELECT_BEST = "random_forest_shallow__stable_4__RANGE"
EXPECTED_PRODUCTION_WINNER = "xgb_baseline_phase96__stable_except_unstable__RANGE"


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_paths(base_dir: str | Path | None) -> dict[str, Path]:
    return {
        "model.pkl": phase9_9_model_path(base_dir),
        "scaler.pkl": phase9_9_scaler_path(base_dir),
        "feature_order.json": phase9_9_feature_order_path(base_dir),
        "config.json": phase9_9_config_path(base_dir),
        "metadata.json": phase9_9_metadata_path(base_dir),
        "freeze_manifest.json": phase9_9_freeze_manifest_path(base_dir),
    }


def snapshot_artifacts(base_dir: str | Path | None) -> dict[str, Any]:
    paths = _artifact_paths(base_dir)
    metadata = _load_json(paths["metadata.json"])
    checksums = {name: _sha256_file(path) for name, path in paths.items() if path.is_file()}
    return {
        "snapshot_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts_root": str(phase9_9_artifacts_root(base_dir)),
        "candidate_id": metadata.get("candidate_id"),
        "experiment_id": metadata.get("experiment_id"),
        "model_type": metadata.get("model_type"),
        "feature_subset": metadata.get("feature_subset"),
        "freeze_authority": metadata.get("freeze_authority"),
        "metadata": metadata,
        "artifact_checksums": checksums,
        "files_present": {name: path.is_file() for name, path in paths.items()},
    }


def _load_baseline(base_dir: str | Path | None, comparison: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(comparison.get("baseline_phase9_8") or {})
    p98 = _load_json(phase9_8_robustness_report_path(base_dir))
    win = _load_json(phase9_8_window_results_path(base_dir))
    baseline["mean_auc_gap"] = load_baseline_numeric(p98, win).get("mean_auc_gap")
    return baseline


def _count_eligible(ranked: list[dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for candidate in ranked:
        if not candidate.get("probability_gate_passed"):
            continue
        acceptance = evaluate_acceptance(candidate, baseline)
        if acceptance.get("final_verdict") == "PASS":
            eligible.append(
                {
                    "experiment_id": candidate.get("experiment_id"),
                    "composite_score": candidate.get("composite_score"),
                    "acceptance": acceptance.get("final_verdict"),
                }
            )
    return eligible


def build_optimizer_execution_report(
    optimizer_result: dict[str, Any],
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    comparison = _load_json(phase9_9_model_comparison_path(base_dir))
    ranked = comparison.get("ranked_candidates") or []
    experiments = comparison.get("experiments") or []
    baseline = _load_baseline(base_dir, comparison)

    candidate_rows: list[dict[str, Any]] = []
    for row in ranked:
        acceptance = evaluate_acceptance(row, baseline)
        candidate_rows.append(
            {
                "experiment_id": row.get("experiment_id"),
                "candidate_id": row.get("candidate_id"),
                "composite_score": row.get("composite_score"),
                "probability_gate_passed": row.get("probability_gate_passed"),
                "acceptance_verdict": acceptance.get("final_verdict"),
                "production_eligible": (
                    bool(row.get("probability_gate_passed"))
                    and acceptance.get("final_verdict") == "PASS"
                ),
            }
        )

    return {
        "phase": "22AK",
        "optimizer_status": optimizer_result.get("status"),
        "optimizer_verdict": optimizer_result.get("final_verdict"),
        "blocked": optimizer_result.get("blocked", False),
        "block_reason": optimizer_result.get("block_reason", ""),
        "candidate_count_reported": len(experiments) or len(ranked),
        "candidate_count_ranked": len(ranked),
        "ranking_top5": [
            {
                "rank": idx + 1,
                "experiment_id": row.get("experiment_id"),
                "composite_score": row.get("composite_score"),
            }
            for idx, row in enumerate(ranked[:5])
        ],
        "candidates": candidate_rows,
        "production_winner_rule": PRODUCTION_WINNER_RULE,
        "report_paths": optimizer_result.get("report_paths", {}),
    }


def build_winner_resolution_report(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    comparison = _load_json(phase9_9_model_comparison_path(base_dir))
    ranked = comparison.get("ranked_candidates") or []
    baseline = _load_baseline(base_dir, comparison)

    select_best_row = select_best(ranked) or {}
    production_winner = select_production_winner(ranked, baseline) or {}
    eligible = _count_eligible(ranked, baseline)

    return {
        "phase": "22AK",
        "select_best_experiment_id": select_best_row.get("experiment_id"),
        "select_best_matches_expected": select_best_row.get("experiment_id") == EXPECTED_SELECT_BEST,
        "production_winner_experiment_id": production_winner.get("experiment_id"),
        "production_winner_matches_expected": (
            production_winner.get("experiment_id") == EXPECTED_PRODUCTION_WINNER
        ),
        "expected_select_best": EXPECTED_SELECT_BEST,
        "expected_production_winner": EXPECTED_PRODUCTION_WINNER,
        "eligible_candidate_count": len(eligible),
        "eligible_candidates": eligible,
        "single_eligible_candidate": len(eligible) == 1,
        "select_best_acceptance": evaluate_acceptance(select_best_row, baseline).get("final_verdict")
        if select_best_row
        else "FAIL",
        "production_winner_acceptance": evaluate_acceptance(production_winner, baseline).get("final_verdict")
        if production_winner
        else "FAIL",
    }


def validate_freeze_contract_complete(
    contract: dict[str, Any],
    *,
    feature_subsets: dict[str, list[str]] | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    required_scalar = (
        "candidate_id",
        "model_type",
        "feature_subset",
        "features",
        "hyperparameters",
        "acceptance_status",
    )
    for key in required_scalar:
        if not contract.get(key):
            errors.append(f"missing:{key}")

    for key in VALIDATION_METRIC_KEYS:
        metrics = contract.get("validation_metrics") or {}
        if metrics.get(key) is None and contract.get(key) is None:
            errors.append(f"missing_validation_metric:{key}")

    for key in PROBABILITY_METRIC_KEYS:
        metrics = contract.get("probability_metrics") or {}
        if metrics.get(key) is None and contract.get(key) is None:
            errors.append(f"missing_probability_metric:{key}")

    fingerprint = (contract.get("metadata") or {}).get("dataset_fingerprint")
    if not fingerprint:
        errors.append("missing_dataset_fingerprint")

    errors.extend(validate_freeze_contract(contract))

    acceptance = contract.get("acceptance_status") or {}
    candidate = {
        "candidate_id": contract.get("candidate_id"),
        "feature_subset": contract.get("feature_subset"),
        **(contract.get("validation_metrics") or {}),
        **(contract.get("probability_metrics") or {}),
    }
    errors.extend(
        validate_accepted_candidate(
            candidate,
            acceptance,
            feature_subsets=feature_subsets or {str(contract.get("feature_subset") or ""): list(contract.get("features") or [])},
        )
    )

    return not errors, sorted(set(errors))


def build_freeze_execution_report(
    *,
    optimizer_result: dict[str, Any],
    before_snapshot: dict[str, Any],
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    contract = optimizer_result.get("freeze_contract") or {}
    contract_ok, contract_errors = validate_freeze_contract_complete(contract)

    after = snapshot_artifacts(base_dir)
    metadata = after.get("metadata") or {}
    feature_order_payload = _load_json(phase9_9_feature_order_path(base_dir))
    feature_order = list(feature_order_payload.get("feature_order") or [])

    manifest = _load_json(phase9_9_freeze_manifest_path(base_dir))
    return {
        "phase": "22AK",
        "freeze_executed": bool(optimizer_result.get("freeze_manifest_path")),
        "freeze_manifest_path": optimizer_result.get("freeze_manifest_path", ""),
        "contract_valid": contract_ok,
        "contract_errors": contract_errors,
        "contract_candidate_id": contract.get("candidate_id"),
        "metadata_candidate_id": metadata.get("candidate_id"),
        "candidate_id_matches": contract.get("candidate_id") == metadata.get("candidate_id"),
        "contract_features": list(contract.get("features") or []),
        "artifact_feature_order": feature_order,
        "feature_order_matches": list(contract.get("features") or []) == feature_order,
        "model_pkl_created": phase9_9_model_path(base_dir).is_file(),
        "manifest_generated": phase9_9_freeze_manifest_path(base_dir).is_file(),
        "manifest_new_candidate": (manifest.get("new_candidate") or {}).get("candidate_id"),
        "before_had_artifacts": any(before_snapshot.get("files_present", {}).values()),
    }


def build_artifact_before_after(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    backup_path: str | None,
) -> dict[str, Any]:
    return {
        "phase": "22AK",
        "old_frozen_candidate": before.get("candidate_id"),
        "new_frozen_candidate": after.get("candidate_id"),
        "old_experiment_id": before.get("experiment_id"),
        "new_experiment_id": after.get("experiment_id"),
        "old_metadata": before.get("metadata"),
        "new_metadata": after.get("metadata"),
        "old_artifact_checksums": before.get("artifact_checksums"),
        "new_artifact_checksums": after.get("artifact_checksums"),
        "checksums_changed": before.get("artifact_checksums") != after.get("artifact_checksums"),
        "backup_location": backup_path,
    }


def _latest_backup_dir(base_dir: str | Path | None) -> Path | None:
    root = phase9_9_backup_root(base_dir)
    if not root.is_dir():
        return None
    dirs = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name)
    return dirs[-1] if dirs else None


def build_backup_validation(
    *,
    base_dir: str | Path | None,
    before_snapshot: dict[str, Any],
) -> dict[str, Any]:
    backup_dir = _latest_backup_dir(base_dir)
    manifest = _load_json(phase9_9_freeze_manifest_path(base_dir))
    backup_path = manifest.get("backup_path") or (str(backup_dir) if backup_dir else None)

    backup_files: dict[str, bool] = {}
    backup_checksums: dict[str, str | None] = {}
    if backup_dir and backup_dir.is_dir():
        for name in ARTIFACT_FILES:
            path = backup_dir / name
            backup_files[name] = path.is_file()
            backup_checksums[name] = _sha256_file(path)

    before_checksums = before_snapshot.get("artifact_checksums") or {}
    restored_core = all(
        backup_checksums.get(name) == before_checksums.get(name)
        for name in ("model.pkl", "scaler.pkl", "feature_order.json", "config.json", "metadata.json")
        if before_checksums.get(name) is not None
    )

    return {
        "phase": "22AK",
        "backup_required": any(before_snapshot.get("files_present", {}).values()),
        "backup_created": backup_dir is not None and backup_dir.is_dir(),
        "backup_path": backup_path,
        "backup_dir": str(backup_dir) if backup_dir else None,
        "backup_files_present": backup_files,
        "backup_checksums_match_before": restored_core,
        "manifest_backup_path": manifest.get("backup_path"),
    }


def build_runtime_validation(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    checks: dict[str, bool] = {}

    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    checks["bundle_loaded"] = bundle.model is not None and bundle.scaler is not None

    probe = {feature: 0.0 for feature in bundle.feature_order}
    integrity = verify_bundle_integrity(bundle, probe)
    checks["checksum_valid"] = integrity.passed
    if not integrity.passed:
        errors.extend(integrity.errors or ["integrity_failed"])

    checks["feature_order_valid"] = bool(bundle.feature_order) and all(
        isinstance(feature, str) for feature in bundle.feature_order
    )
    checks["phase9_feature_order_file"] = phase9_9_feature_order_path(base_dir).is_file()

    metadata = bundle.metadata or {}
    checks["phase9_fingerprint"] = metadata.get("dataset_fingerprint") == EXPECTED_DATASET_FINGERPRINT
    checks["freeze_authority_present"] = metadata.get("freeze_authority") == PRODUCTION_WINNER_RULE
    if not checks["phase9_fingerprint"]:
        errors.append("phase9_fingerprint_mismatch")
    if not checks["freeze_authority_present"]:
        errors.append("freeze_authority_missing")

    healthgate_phase9_passes = all(
        checks.get(key, False)
        for key in (
            "bundle_loaded",
            "checksum_valid",
            "feature_order_valid",
            "phase9_feature_order_file",
            "phase9_fingerprint",
        )
    )
    checks["healthgate_phase9_passes"] = healthgate_phase9_passes

    return {
        "phase": "22AK",
        "checks": checks,
        "errors": errors,
        "healthgate_phase9_passes": healthgate_phase9_passes,
        "candidate_id": metadata.get("candidate_id"),
        "experiment_id": metadata.get("experiment_id"),
        "feature_count": len(bundle.feature_order),
    }


def determine_verdict(
    *,
    optimizer_report: dict[str, Any],
    winner_report: dict[str, Any],
    freeze_report: dict[str, Any],
    backup_report: dict[str, Any],
    runtime_report: dict[str, Any],
) -> str:
    if optimizer_report.get("blocked"):
        return "FREEZE_EXECUTION_BLOCKED"
    if optimizer_report.get("optimizer_verdict") != "PASS":
        return "FREEZE_EXECUTION_BLOCKED"
    if not winner_report.get("production_winner_matches_expected"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not winner_report.get("single_eligible_candidate"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not freeze_report.get("contract_valid"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not freeze_report.get("freeze_executed"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not freeze_report.get("candidate_id_matches"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not freeze_report.get("feature_order_matches"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not freeze_report.get("manifest_generated"):
        return "FREEZE_EXECUTION_BLOCKED"
    if backup_report.get("backup_required") and not backup_report.get("backup_created"):
        return "FREEZE_EXECUTION_BLOCKED"
    if not runtime_report.get("healthgate_phase9_passes"):
        return "FREEZE_EXECUTION_BLOCKED"
    return "MODEL_FROZEN_SUCCESSFULLY"


def run_freeze_execution(
    *,
    base_dir: str | Path | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = 42,
    run_optimizer: bool = True,
) -> dict[str, Any]:
    from tradingbot.ml.research.robustness_optimizer import RobustnessOptimizer

    before_snapshot = snapshot_artifacts(base_dir)
    backup_dirs_before = {
        p.name for p in phase9_9_backup_root(base_dir).iterdir() if p.is_dir()
    } if phase9_9_backup_root(base_dir).is_dir() else set()

    optimizer_payload: dict[str, Any] = {}
    if run_optimizer:
        optimizer = RobustnessOptimizer(base_dir=base_dir, seed=seed)
        result = optimizer.run(symbol, timeframe, freeze_on_pass=True)
        optimizer_payload = result.to_dict()

    after_snapshot = snapshot_artifacts(base_dir)
    backup_report = build_backup_validation(base_dir=base_dir, before_snapshot=before_snapshot)

    backup_dirs_after = {
        p.name for p in phase9_9_backup_root(base_dir).iterdir() if p.is_dir()
    } if phase9_9_backup_root(base_dir).is_dir() else set()
    new_backup_names = sorted(backup_dirs_after - backup_dirs_before)
    if new_backup_names:
        backup_report["new_backup_dir"] = str(phase9_9_backup_root(base_dir) / new_backup_names[-1])

    optimizer_report = build_optimizer_execution_report(optimizer_payload, base_dir=base_dir)
    winner_report = build_winner_resolution_report(base_dir=base_dir)
    freeze_report = build_freeze_execution_report(
        optimizer_result=optimizer_payload,
        before_snapshot=before_snapshot,
        base_dir=base_dir,
    )
    artifact_report = build_artifact_before_after(
        before_snapshot,
        after_snapshot,
        backup_path=backup_report.get("backup_path"),
    )
    runtime_report = build_runtime_validation(base_dir=base_dir)

    verdict = determine_verdict(
        optimizer_report=optimizer_report,
        winner_report=winner_report,
        freeze_report=freeze_report,
        backup_report=backup_report,
        runtime_report=runtime_report,
    )

    return {
        "optimizer_execution_report": optimizer_report,
        "winner_resolution_report": winner_report,
        "freeze_execution_report": freeze_report,
        "artifact_before_after": artifact_report,
        "runtime_validation": runtime_report,
        "backup_validation": backup_report,
        "verdict": verdict,
        "before_snapshot": before_snapshot,
        "after_snapshot": after_snapshot,
    }
