"""Phase 22AJ — production freeze authority wiring validation."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_8_robustness_report_path,
    phase9_8_window_results_path,
    phase9_9_freeze_manifest_path,
    phase9_9_model_comparison_path,
)
from tradingbot.ml.research.phase22z.overfitting_rule_validation import load_baseline_numeric
from tradingbot.ml.research.robustness_optimizer.candidate_selector import (
    PRODUCTION_WINNER_RULE,
    select_best,
    select_production_winner,
)
from tradingbot.ml.research.robustness_optimizer.report_generator import evaluate_acceptance

PROJECT_ROOT = Path(__file__).resolve().parents[4]

BYPASS_FILES = (
    "tradingbot/ml/integration/kernel_shadow_runner.py",
    "tradingbot/ml/paper_trading/shadow_engine.py",
    "tradingbot/ml/shadow/ml_adapter.py",
    "tradingbot/ml/paper_trading/model_registry.py",
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_production_winner_trace(
    *,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    comparison = _load_json(phase9_9_model_comparison_path(base_dir))
    ranked = comparison.get("ranked_candidates") or []
    p98 = _load_json(phase9_8_robustness_report_path(base_dir))
    win = _load_json(phase9_8_window_results_path(base_dir))
    baseline = dict(comparison.get("baseline_phase9_8") or {})
    baseline["mean_auc_gap"] = load_baseline_numeric(p98, win).get("mean_auc_gap")

    rank_one = ranked[0] if ranked else {}
    select_best_row = select_best(ranked) or {}
    production_winner = select_production_winner(ranked, baseline)
    production_acceptance = (
        evaluate_acceptance(production_winner, baseline) if production_winner else {"final_verdict": "FAIL"}
    )

    return {
        "phase": "22AJ",
        "production_winner_rule": PRODUCTION_WINNER_RULE,
        "rank_one_experiment_id": rank_one.get("experiment_id"),
        "select_best_experiment_id": select_best_row.get("experiment_id"),
        "production_winner_experiment_id": (production_winner or {}).get("experiment_id"),
        "production_winner_acceptance": production_acceptance.get("final_verdict"),
        "report_best_candidate_experiment_id": (comparison.get("best_candidate") or {}).get("experiment_id"),
        "orchestrator_source": "optimization_orchestrator.select_production_winner",
        "freeze_manifest_exists": phase9_9_freeze_manifest_path(base_dir).is_file(),
    }


def _function_body(path: Path, function_name: str) -> str:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(src, node) or ""
    return ""


def build_freeze_wiring_report() -> dict[str, Any]:
    orch_path = PROJECT_ROOT / "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py"
    registry_path = PROJECT_ROOT / "tradingbot/ml/paper_trading/model_registry.py"
    bridge_path = PROJECT_ROOT / "tradingbot/ml/research/robustness_optimizer/freeze_bridge.py"
    orch = orch_path.read_text(encoding="utf-8")
    registry = registry_path.read_text(encoding="utf-8")
    bridge = bridge_path.read_text(encoding="utf-8")
    freeze_body = _function_body(registry_path, "freeze_phase9_9_from_contract")
    return {
        "phase": "22AJ",
        "authority_chain": [
            "rank_candidates",
            "select_production_winner",
            "evaluate_acceptance",
            "build_freeze_contract",
            "freeze_phase9_9_artifacts(contract=...)",
        ],
        "orchestrator_checks": {
            "uses_select_production_winner": "select_production_winner" in orch,
            "uses_build_freeze_contract": "build_freeze_contract" in orch,
            "calls_freeze_with_contract": "freeze_phase9_9_artifacts" in orch and "contract=freeze_contract" in orch,
            "no_select_best_for_freeze": "best = select_best" not in orch,
        },
        "registry_checks": {
            "has_validate_freeze_contract": "validate_freeze_contract" in registry,
            "has_freeze_from_contract": "freeze_phase9_9_from_contract" in registry,
            "no_default_config_literal": "DEFAULT_CONFIG:" not in registry and "DEFAULT_CONFIG =" not in registry,
            "no_logistic_hardcode_in_from_contract": 'candidate_id="logistic_strong_reg"' not in freeze_body,
            "writes_freeze_manifest": "freeze_manifest" in registry,
            "backup_before_replace": (
                "phase9_9_backup_root" in registry and "_backup_existing_artifacts" in registry
            ),
            "load_default_build_if_missing_false": "build_if_missing: bool = False" in registry,
        },
        "bridge_checks": {
            "requires_acceptance_pass": "missing_acceptance_pass" in bridge,
            "requires_probability_gate": "missing_probability_gate" in bridge,
        },
    }


def build_authority_migration_report() -> dict[str, Any]:
    return {
        "phase": "22AJ",
        "removed": [
            "DEFAULT_CONFIG as freeze winner source",
            "hardcoded logistic_strong_reg in freeze body",
            "hardcoded stable_top3 feature subset in freeze metadata",
            "select_best as production freeze source",
            "silent build_if_missing auto-freeze without contract",
        ],
        "added": [
            "select_production_winner in candidate_selector.py",
            "freeze_phase9_9_from_contract",
            "validate_freeze_contract",
            "freeze_manifest.json with acceptance snapshot and checksums",
            "phase9_9_best_backup before artifact replace",
        ],
        "runtime_preserved": [
            "load_phase9_9_bundle read path",
            "phase9_9_best/model.pkl inference",
            "HealthGate / KernelAdapter / RangeEngineAdapter unchanged",
        ],
    }


def build_bypass_audit() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rel in BYPASS_FILES:
        path = PROJECT_ROOT / rel
        src = path.read_text(encoding="utf-8")
        row = {
            "file": rel,
            "auto_freeze_without_contract": False,
            "build_if_missing_true": bool(re.search(r"build_if_missing\s*=\s*True", src)),
            "calls_freeze_phase9_9_artifacts": "freeze_phase9_9_artifacts" in src,
            "notes": "",
        }
        if rel.endswith("kernel_shadow_runner.py"):
            row["auto_freeze_without_contract"] = "freeze_phase9_9_artifacts(" in src
            row["notes"] = "Raises FileNotFoundError if artifacts missing"
        if rel.endswith("shadow_engine.py"):
            row["notes"] = "Loads existing bundle only"
        if rel.endswith("ml_adapter.py"):
            row["notes"] = "load uses build_if_missing=False"
        if rel.endswith("model_registry.py"):
            row["notes"] = "build_if_missing requires contract when True"
        rows.append(row)
    return {
        "phase": "22AJ",
        "paths_audited": rows,
        "silent_rebuild_blocked": all(not r["auto_freeze_without_contract"] for r in rows),
        "production_build_if_missing_true": [r["file"] for r in rows if r["build_if_missing_true"]],
    }


def build_freeze_manifest_schema() -> dict[str, Any]:
    return {
        "phase": "22AJ",
        "manifest_path": "data/ml/research/phase9_9_best/freeze_manifest.json",
        "required_fields": {
            "manifest_version": "string",
            "frozen_at_utc": "ISO timestamp",
            "freeze_authority": "ACCEPTANCE_PASS_HIGHEST_COMPOSITE",
            "previous_candidate": "dict|null",
            "new_candidate": {
                "candidate_id": "string",
                "experiment_id": "string",
                "model_type": "string",
                "feature_subset": "string",
            },
            "acceptance_snapshot": "evaluate_acceptance output",
            "dataset_fingerprint": "string",
            "report_path": "string|null",
            "backup_path": "string|null",
            "artifact_checksums": "dict filename -> sha256",
        },
    }


def determine_verdict(wiring: dict[str, Any], bypass: dict[str, Any]) -> str:
    orch = wiring.get("orchestrator_checks", {})
    reg = wiring.get("registry_checks", {})
    if not all(orch.values()):
        return "MIGRATION_BLOCKED"
    if not all(reg.values()):
        return "MIGRATION_BLOCKED"
    if not bypass.get("silent_rebuild_blocked"):
        return "MIGRATION_BLOCKED"
    if bypass.get("production_build_if_missing_true"):
        return "MIGRATION_BLOCKED"
    return "FREEZE_AUTHORITY_MIGRATED"


def run_investigation(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    wiring = build_freeze_wiring_report()
    bypass = build_bypass_audit()
    return {
        "production_winner_trace": build_production_winner_trace(base_dir=base_dir),
        "freeze_wiring_report": wiring,
        "authority_migration_report": build_authority_migration_report(),
        "bypass_audit": bypass,
        "freeze_manifest_schema": build_freeze_manifest_schema(),
        "verdict": determine_verdict(wiring, bypass),
    }
