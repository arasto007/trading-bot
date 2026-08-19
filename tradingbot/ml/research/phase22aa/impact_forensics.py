"""Phase 22AA — overfitting_risk_decreased impact radius forensics."""

from __future__ import annotations

from typing import Any

# Repository constants from robustness_analyzer.assess_overfitting_risk
ASSESS_OVERFITTING_THRESHOLDS = {
    "HIGH": {
        "mean_auc_gap_gt": 0.12,
        "robustness_score_lt": 45,
        "mean_degradation_gt": 0.25,
    },
    "MEDIUM": {
        "mean_auc_gap_gt": 0.06,
        "robustness_score_lt": 70,
        "mean_degradation_gt": 0.12,
    },
}

ACCEPTANCE_THRESHOLDS = {
    "profitable_windows_minimum": 4,
    "window_count_minimum": 4,
    "robustness_improved_strict_gt": True,
}

RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def build_call_chain() -> dict[str, Any]:
    return {
        "phase": "22AA",
        "anchor_rule": "overfitting_risk_decreased",
        "anchor_implementation": {
            "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "evaluate_acceptance",
            "helper": "_risk_improved",
            "formula": "RISK_ORDER[best_risk] < RISK_ORDER[baseline_risk]",
        },
        "upstream_chain": [
            {
                "level": -4,
                "file": "scripts/train_model.py",
                "function": "main",
                "trigger": "--phase9-9",
                "outputs": ["RobustnessOptimizer.run exit code"],
            },
            {
                "level": -3,
                "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                "function": "RobustnessOptimizer.run",
                "inputs": ["symbol", "timeframe", "dataset_v2", "phase9_8 baseline JSON"],
                "outputs": ["RobustnessOptimizationResult"],
                "calls": ["run_candidate_grid", "rank_candidates", "select_best", "evaluate_acceptance", "save_reports"],
            },
            {
                "level": -3,
                "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                "function": "_load_phase98_baseline",
                "inputs": ["phase9_8_walk_forward_report.json"],
                "outputs": ["robustness_score", "overfitting_risk", "mean_profit_factor", "mean_expectancy"],
                "side_effects": "read-only",
            },
            {
                "level": -2,
                "file": "tradingbot/ml/research/robustness_optimizer/walk_forward_optimizer.py",
                "function": "run_walk_forward_experiment",
                "inputs": ["candidate", "feature_cols", "regime"],
                "outputs": ["experiment dict with overfitting_risk, mean_auc_gap, robustness_score"],
                "calls": ["validate_window_candidate", "aggregate_window_metrics", "analyze_robustness"],
            },
            {
                "level": -1,
                "file": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                "function": "assess_overfitting_risk",
                "inputs": ["windows", "robustness_score"],
                "outputs": ["LOW | MEDIUM | HIGH label"],
                "dependencies": ["train_val_auc_gap", "performance_degradation per window"],
            },
            {
                "level": -1,
                "file": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
                "function": "select_best",
                "inputs": ["ranked candidates with overfitting_risk field"],
                "outputs": ["best candidate dict"],
                "note": "Uses probability_gate_passed; does NOT call evaluate_acceptance",
            },
        ],
        "anchor": {
            "level": 0,
            "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "evaluate_acceptance",
            "inputs": {
                "best": "selected candidate dict (includes overfitting_risk from walk-forward)",
                "baseline": "Phase 9.8 summary from _load_phase98_baseline",
            },
            "outputs": {
                "checks.overfitting_risk_decreased": "bool",
                "final_verdict": "PASS if all checks true else FAIL",
            },
            "side_effects": "none (pure function)",
        },
        "downstream_chain": [
            {
                "level": 1,
                "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                "function": "RobustnessOptimizer.run",
                "consumes": ["acceptance.final_verdict", "acceptance.checks"],
                "outputs": ["RobustnessOptimizationResult.final_verdict", "status"],
            },
            {
                "level": 1,
                "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                "function": "save_reports",
                "consumes": ["acceptance dict"],
                "outputs": [
                    "data/ml/reports/phase9_9_robustness_report.json",
                    "data/ml/reports/phase9_9_model_comparison.json",
                ],
                "side_effects": "writes JSON reports",
            },
            {
                "level": 2,
                "file": "scripts/train_model.py",
                "function": "main",
                "consumes": ["result.final_verdict"],
                "outputs": ["process exit code 0|1"],
            },
            {
                "level": 2,
                "file": "data/ml/reports/phase9_9_robustness_report.json",
                "function": "artifact",
                "consumes": ["acceptance.checks.overfitting_risk_decreased"],
                "outputs": ["human/forensics readers (phase22y/z)"],
            },
        ],
        "explicitly_not_in_chain": [
            {
                "file": "tradingbot/ml/paper_trading/model_registry.py",
                "function": "freeze_phase9_9_artifacts",
                "reason": "Hardcoded retrain path; never reads evaluate_acceptance or overfitting_risk_decreased",
            },
            {
                "file": "tradingbot/ml/integration/health_gate.py",
                "function": "run_pre_decision_health",
                "reason": "Live pre-decision bundle integrity; unrelated to Phase 9.9 acceptance",
            },
            {
                "file": "tradingbot/kernel",
                "reason": "No import of evaluate_acceptance per phase isolation rules",
            },
        ],
    }


def build_dependency_graph() -> dict[str, Any]:
    nodes = [
        {"id": "train_model_cli", "path": "scripts/train_model.py", "layer": "cli"},
        {"id": "robustness_optimizer", "path": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py", "layer": "orchestrator"},
        {"id": "walk_forward_optimizer", "path": "tradingbot/ml/research/robustness_optimizer/walk_forward_optimizer.py", "layer": "experiment"},
        {"id": "window_validator", "path": "tradingbot/ml/research/robustness_optimizer/window_validator.py", "layer": "validation"},
        {"id": "model_validator", "path": "tradingbot/ml/research/walk_forward/model_validator.py", "layer": "shared_validation"},
        {"id": "walk_forward_metrics", "path": "tradingbot/ml/research/walk_forward/walk_forward_metrics.py", "layer": "metrics"},
        {"id": "robustness_analyzer", "path": "tradingbot/ml/research/walk_forward/robustness_analyzer.py", "layer": "robustness"},
        {"id": "candidate_selector", "path": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py", "layer": "ranking"},
        {"id": "report_generator", "path": "tradingbot/ml/research/robustness_optimizer/report_generator.py", "layer": "acceptance"},
        {"id": "phase98_report", "path": "data/ml/reports/phase9_8_walk_forward_report.json", "layer": "artifact"},
        {"id": "phase99_report", "path": "data/ml/reports/phase9_9_robustness_report.json", "layer": "artifact"},
        {"id": "freeze_registry", "path": "tradingbot/ml/paper_trading/model_registry.py", "layer": "freeze"},
        {"id": "health_gate", "path": "tradingbot/ml/integration/health_gate.py", "layer": "live"},
        {"id": "walk_forward_engine", "path": "tradingbot/ml/research/walk_forward/walk_forward_engine.py", "layer": "phase98"},
    ]
    edges = [
        {"from": "train_model_cli", "to": "robustness_optimizer", "relation": "invokes --phase9-9"},
        {"from": "robustness_optimizer", "to": "walk_forward_optimizer", "relation": "run_candidate_grid"},
        {"from": "walk_forward_optimizer", "to": "window_validator", "relation": "per-window validation"},
        {"from": "window_validator", "to": "model_validator", "relation": "_ml_metrics, _simulate_trades"},
        {"from": "walk_forward_optimizer", "to": "walk_forward_metrics", "relation": "aggregate_window_metrics"},
        {"from": "walk_forward_optimizer", "to": "robustness_analyzer", "relation": "analyze_robustness → overfitting_risk label"},
        {"from": "robustness_optimizer", "to": "candidate_selector", "relation": "rank_candidates, select_best"},
        {"from": "robustness_optimizer", "to": "report_generator", "relation": "evaluate_acceptance, save_reports"},
        {"from": "phase98_report", "to": "report_generator", "relation": "baseline overfitting_risk input"},
        {"from": "robustness_analyzer", "to": "report_generator", "relation": "candidate overfitting_risk label"},
        {"from": "report_generator", "to": "phase99_report", "relation": "writes acceptance.checks"},
        {"from": "robustness_optimizer", "to": "train_model_cli", "relation": "final_verdict exit code"},
        {"from": "walk_forward_engine", "to": "phase98_report", "relation": "Phase 9.8 produces baseline (no acceptance rule)"},
        {"from": "freeze_registry", "to": "health_gate", "relation": "load_phase9_9_bundle only (orthogonal to acceptance)"},
    ]
    return {
        "phase": "22AA",
        "anchor": "overfitting_risk_decreased",
        "nodes": nodes,
        "edges": edges,
        "upstream_depth": 4,
        "downstream_depth": 2,
    }


def build_threshold_map() -> dict[str, Any]:
    def impact(subsystem: str, affected: bool, note: str) -> dict[str, Any]:
        return {"subsystem": subsystem, "affected_if_threshold_changes": affected, "note": note}

    entries = []
    for name, thresholds in ASSESS_OVERFITTING_THRESHOLDS.items():
        entries.append(
            {
                "name": f"assess_overfitting_risk_{name}",
                "defined_in": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                "function": "assess_overfitting_risk",
                "constants": thresholds,
                "used_by": [
                    "analyze_robustness",
                    "walk_forward_optimizer.run_walk_forward_experiment",
                    "WalkForwardEngine (Phase 9.8)",
                ],
                "depends_on": ["per-window train_val_auc_gap", "performance_degradation", "robustness_score"],
                "impact_if_changed": [
                    impact("Phase 9.8", True, "Changes overfitting_risk label in phase9_8_walk_forward_report.json baseline"),
                    impact("Phase 9.9 walk-forward", True, "Changes candidate overfitting_risk labels fed into evaluate_acceptance"),
                    impact("Phase 9.9 selection ranking", True, "candidate_selector tie-breaker uses overfitting_risk ordinal"),
                    impact("Phase 9.9 acceptance", True, "Indirect: label change affects overfitting_risk_decreased boolean"),
                    impact("Freeze", False, "freeze_phase9_9_artifacts does not read labels"),
                    impact("Health Gate", False, "No overfitting_risk in health_gate.py"),
                ],
            }
        )

    entries.append(
        {
            "name": "overfitting_risk_decreased_ordinal",
            "defined_in": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "_risk_improved",
            "constants": {"RISK_ORDER": RISK_ORDER},
            "used_by": ["evaluate_acceptance only"],
            "depends_on": ["baseline.overfitting_risk from Phase 9.8", "best.overfitting_risk from walk-forward"],
            "impact_if_changed": [
                impact("Phase 9.8", False, "Phase 9.8 does not call evaluate_acceptance"),
                impact("Phase 9.9 walk-forward", False, "Walk-forward produces labels; rule consumes them"),
                impact("Phase 9.9 selection", False, "select_best does not use this check"),
                impact("Phase 9.9 acceptance", True, "Direct: changes PASS/FAIL verdict"),
                impact("Freeze", False, "Decoupled hardcoded freeze path"),
                impact("Health Gate", False, "Unrelated"),
            ],
        }
    )

    entries.append(
        {
            "name": "robustness_score_gap_penalty",
            "defined_in": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
            "function": "compute_robustness_score",
            "constants": {"gap_penalty_multiplier": 4.0, "weights": "0.30/0.30/0.25/0.15"},
            "impact_if_changed": [
                impact("Phase 9.8", True, "Baseline robustness_score in report"),
                impact("Phase 9.9 acceptance", True, "Indirect via robustness_improved check, not overfitting_risk_decreased directly"),
            ],
        }
    )

    return {"phase": "22AA", "thresholds": entries}


def build_duplicate_logic() -> dict[str, Any]:
    return {
        "phase": "22AA",
        "duplicates": [
            {
                "pattern": "ordinal_risk_order_LOW_MEDIUM_HIGH",
                "instances": [
                    {
                        "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                        "function": "_risk_improved",
                        "usage": "acceptance overfitting_risk_decreased",
                    },
                    {
                        "file": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
                        "function": "rank_candidates sort_key",
                        "usage": "tie-breaker only (lower order preferred)",
                    },
                ],
                "risk": "MEDIUM — changing RISK_ORDER in one file without the other desynchronizes ranking vs acceptance",
            },
            {
                "pattern": "assess_overfitting_risk_label",
                "instances": [
                    {
                        "file": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                        "function": "assess_overfitting_risk",
                        "usage": "single source of truth for LOW/MEDIUM/HIGH",
                    }
                ],
                "risk": "LOW — single implementation; consumed by Phase 9.8 and 9.9",
            },
            {
                "pattern": "evaluate_acceptance_function_name",
                "instances": [
                    {
                        "file": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                        "function": "evaluate_acceptance",
                        "usage": "Phase 9.9 acceptance (includes overfitting_risk_decreased)",
                    },
                    {
                        "file": "tradingbot/ml/research/phase17b/acceptance.py",
                        "function": "evaluate_acceptance",
                        "usage": "Phase 17B retrain lab — unrelated checks, no overfitting_risk_decreased",
                    },
                ],
                "risk": "SAFE — name collision only; independent implementations",
            },
            {
                "pattern": "train_val_auc_gap_computation",
                "instances": [
                    {
                        "file": "tradingbot/ml/research/robustness_optimizer/window_validator.py",
                        "function": "validate_window_candidate",
                    },
                    {
                        "file": "tradingbot/ml/research/walk_forward/model_validator.py",
                        "function": "validate_window",
                    },
                ],
                "risk": "HIGH — shared logic pattern; gap feeds assess_overfitting_risk",
            },
            {
                "pattern": "freeze_vs_selection",
                "instances": [
                    {
                        "file": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
                        "usage": "select_best + evaluate_acceptance",
                    },
                    {
                        "file": "tradingbot/ml/paper_trading/model_registry.py",
                        "function": "freeze_phase9_9_artifacts",
                        "usage": "hardcoded logistic + 3 features; no acceptance",
                    },
                ],
                "risk": "CRITICAL — production frozen artifact bypasses acceptance pipeline",
            },
        ],
    }


def build_architecture_boundary() -> dict[str, Any]:
    return {
        "phase": "22AA",
        "anchor_change": "overfitting_risk_decreased rule logic",
        "must_change_together": [
            {
                "files": [
                    "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                ],
                "reason": "Single implementation of _risk_improved / evaluate_acceptance check",
            },
            {
                "files": [
                    "tradingbot/ml/research/robustness_optimizer/report_generator.py",
                    "tests/test_ml_research_phase9_9.py",
                    "tests/test_phase22x.py",
                ],
                "reason": "Acceptance tests assert evaluate_acceptance behavior",
                "condition": "if acceptance semantics change",
            },
        ],
        "should_change_together": [
            {
                "files": [
                    "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
                ],
                "reason": "If ordinal risk semantics change, rank tie-breaker RISK_ORDER should stay aligned",
            },
            {
                "files": [
                    "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
                ],
                "reason": "If switching from ordinal label to numeric gap comparison, label producer thresholds may need coordinated update",
                "condition": "only when label strategy changes, not for pure acceptance formula tweak",
            },
            {
                "files": [
                    "tradingbot/ml/research/phase22y/",
                    "tradingbot/ml/research/phase22z/",
                ],
                "reason": "Forensics document current rule; update after rule change",
            },
        ],
        "must_not_change": [
            "tradingbot/kernel/",
            "tradingbot/execution/",
            "tradingbot/risk/",
            "tradingbot/ml/integration/health_gate.py",
            "tradingbot/ml/paper_trading/model_registry.py freeze path (unless separate approved freeze-integration phase)",
            "LiveRunner",
            "FeatureBuilder",
            "Label pipeline",
        ],
        "boundary_statement": (
            "overfitting_risk_decreased lives entirely inside Phase 9.9 research acceptance "
            "(report_generator → optimization_orchestrator → JSON reports → train_model exit code). "
            "It does not gate freeze_phase9_9_artifacts, live HealthGate, or TradingKernel."
        ),
    }


def build_impact_radius() -> dict[str, Any]:
    items = [
        {
            "id": "report_generator_evaluate_acceptance",
            "path": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "evaluate_acceptance",
            "classification": "CRITICAL",
            "reason": "Direct implementation of overfitting_risk_decreased",
        },
        {
            "id": "report_generator_risk_improved",
            "path": "tradingbot/ml/research/robustness_optimizer/report_generator.py",
            "function": "_risk_improved",
            "classification": "CRITICAL",
            "reason": "Ordinal comparison formula",
        },
        {
            "id": "optimization_orchestrator",
            "path": "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py",
            "function": "RobustnessOptimizer.run",
            "classification": "HIGH",
            "reason": "Calls evaluate_acceptance; sets final_verdict consumed by CLI",
        },
        {
            "id": "robustness_analyzer_assess",
            "path": "tradingbot/ml/research/walk_forward/robustness_analyzer.py",
            "function": "assess_overfitting_risk",
            "classification": "HIGH",
            "reason": "Produces overfitting_risk labels consumed by acceptance (indirect)",
        },
        {
            "id": "candidate_selector_rank",
            "path": "tradingbot/ml/research/robustness_optimizer/candidate_selector.py",
            "function": "rank_candidates",
            "classification": "MEDIUM",
            "reason": "Duplicate RISK_ORDER tie-breaker; not acceptance gate",
        },
        {
            "id": "walk_forward_optimizer",
            "path": "tradingbot/ml/research/robustness_optimizer/walk_forward_optimizer.py",
            "function": "run_walk_forward_experiment",
            "classification": "MEDIUM",
            "reason": "Propagates overfitting_risk into experiment dict",
        },
        {
            "id": "phase99_robustness_report",
            "path": "data/ml/reports/phase9_9_robustness_report.json",
            "classification": "MEDIUM",
            "reason": "Artifact stores acceptance.checks; regenerated each run",
        },
        {
            "id": "train_model_cli",
            "path": "scripts/train_model.py",
            "function": "main --phase9-9",
            "classification": "MEDIUM",
            "reason": "Exit code reflects acceptance final_verdict",
        },
        {
            "id": "walk_forward_engine_98",
            "path": "tradingbot/ml/research/walk_forward/walk_forward_engine.py",
            "classification": "MEDIUM",
            "reason": "Produces baseline overfitting_risk label only",
        },
        {
            "id": "phase98_walk_forward_report",
            "path": "data/ml/reports/phase9_8_walk_forward_report.json",
            "classification": "MEDIUM",
            "reason": "Baseline overfitting_risk=HIGH input to rule",
        },
        {
            "id": "freeze_phase9_9",
            "path": "tradingbot/ml/paper_trading/model_registry.py",
            "function": "freeze_phase9_9_artifacts",
            "classification": "SAFE",
            "reason": "No import or call to evaluate_acceptance",
        },
        {
            "id": "health_gate",
            "path": "tradingbot/ml/integration/health_gate.py",
            "classification": "SAFE",
            "reason": "Bundle integrity / feature checks only",
        },
        {
            "id": "kernel",
            "path": "tradingbot/kernel/",
            "classification": "SAFE",
            "reason": "No dependency on Phase 9.9 acceptance",
        },
        {
            "id": "phase22y_forensics",
            "path": "tradingbot/ml/research/phase22y/",
            "classification": "SAFE",
            "reason": "Read-only analysis importing evaluate_acceptance",
        },
        {
            "id": "phase17b_acceptance",
            "path": "tradingbot/ml/research/phase17b/acceptance.py",
            "classification": "SAFE",
            "reason": "Independent acceptance for trend retrain lab",
        },
    ]
    summary = {
        "CRITICAL": sum(1 for i in items if i["classification"] == "CRITICAL"),
        "HIGH": sum(1 for i in items if i["classification"] == "HIGH"),
        "MEDIUM": sum(1 for i in items if i["classification"] == "MEDIUM"),
        "SAFE": sum(1 for i in items if i["classification"] == "SAFE"),
    }
    return {"phase": "22AA", "items": items, "summary": summary}


def run_impact_forensics() -> dict[str, Any]:
    return {
        "call_chain": build_call_chain(),
        "dependency_graph": build_dependency_graph(),
        "threshold_map": build_threshold_map(),
        "duplicate_logic": build_duplicate_logic(),
        "architecture_boundary": build_architecture_boundary(),
        "impact_radius": build_impact_radius(),
        "verdict": "ACCEPTANCE_RULE_ISOLATED_TO_PHASE9_9_RESEARCH_PIPELINE",
    }
