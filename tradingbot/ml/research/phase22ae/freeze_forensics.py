"""Phase 22AE — why freeze_phase9_9_artifacts freezes logistic_strong_reg."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
MODEL_REGISTRY = PROJECT_ROOT / "tradingbot/ml/paper_trading/model_registry.py"
OPTIMIZER = PROJECT_ROOT / "tradingbot/ml/research/robustness_optimizer/optimization_orchestrator.py"
TRAIN_CLI = PROJECT_ROOT / "scripts/train_model.py"

SEARCH_TERMS = (
    "DEFAULT_CONFIG",
    "logistic_strong_reg",
    "stable_top3",
    "phase9_9_best",
    "freeze_phase9_9_artifacts",
)

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "archive"}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _read(rel: str | Path) -> str:
    return Path(rel if isinstance(rel, Path) else PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _scan_repository() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {t: [] for t in SEARCH_TERMS}
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".json", ".md"}:
            continue
        if any(p in SKIP_DIRS for p in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not any(t in text for t in SEARCH_TERMS):
            continue
        tree = None
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
        for i, line in enumerate(text.splitlines(), 1):
            for term in SEARCH_TERMS:
                if term not in line:
                    continue
                fn = None
                if tree:
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if node.lineno <= i <= getattr(node, "end_lineno", node.lineno):
                                fn = node.name
                out[term].append(
                    {
                        "file": _rel(path),
                        "function": fn or "(module)",
                        "line": i,
                        "snippet": line.strip()[:160],
                    }
                )
    return out


def _parse_default_config_literal() -> dict[str, Any]:
    tree = ast.parse(_read(MODEL_REGISTRY))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEFAULT_CONFIG":
                    return ast.literal_eval(node.value)
    return {}


def build_freeze_trace() -> dict[str, Any]:
    """STEP 1 — complete freeze_phase9_9_artifacts trace."""
    src = _read(MODEL_REGISTRY)
    return {
        "phase": "22AE",
        "anchor_function": "freeze_phase9_9_artifacts",
        "anchor_file": _rel(MODEL_REGISTRY),
        "signature": {
            "parameters": [
                {"name": "df", "type": "pd.DataFrame", "required": True},
                {"name": "base_dir", "type": "str | Path | None", "default": None},
                {"name": "seed", "type": "int", "default": "DEFAULT_SEED (42)"},
                {"name": "config", "type": "dict | None", "default": None},
            ],
        },
        "call_graph": [
            {
                "step": 1,
                "function": "freeze_phase9_9_artifacts",
                "action": "cfg = dict(config or DEFAULT_CONFIG)",
                "line": 100,
                "object": "cfg dict",
            },
            {
                "step": 2,
                "function": "_training_frame",
                "callees": ["filter_resolved_labels", "assign_market_regime", "apply_event_filter"],
                "action": "filter RANGE rows using cfg['regime'] and cfg['event_filter']",
                "line": 102,
            },
            {
                "step": 3,
                "function": "freeze_phase9_9_artifacts",
                "action": "chronological 85% train split",
                "line": "106-108",
            },
            {
                "step": 4,
                "function": "StandardScaler.fit",
                "action": "fit on cfg['features'] columns only",
                "line": "110-113",
            },
            {
                "step": 5,
                "function": "ModelCandidateConfig",
                "action": "HARDCODED candidate_id='logistic_strong_reg', model_name='logistic'",
                "line": "115-118",
                "note": "Does NOT read cfg['model'] or optimizer best_candidate",
            },
            {
                "step": 6,
                "function": "create_regularized_model",
                "file": "tradingbot/ml/research/robustness_optimizer/model_regularization.py",
                "action": "build LogisticRegression(C=cfg parameters default 0.1)",
                "line": 120,
            },
            {
                "step": 7,
                "function": "model.fit",
                "action": "train on scaled 85% slice — NOT walk-forward winner retrain path",
                "line": 121,
            },
            {
                "step": 8,
                "function": "joblib.dump + write_text",
                "artifacts": ["model.pkl", "scaler.pkl", "feature_order.json", "config.json", "metadata.json"],
                "line": "125-142",
            },
            {
                "step": 9,
                "function": "_load_phase99_score",
                "action": "reads ONLY robustness_score from phase9_9_robustness_report.json",
                "line": "140",
                "note": "Does not read best_candidate.candidate_id or experiment_id",
            },
        ],
        "hardcoded_metadata_fields": {
            "candidate_id": "logistic_strong_reg",
            "feature_subset": "stable_top3",
            "phase": "9.9",
        },
        "constants_used": {
            "DEFAULT_CONFIG": _parse_default_config_literal(),
            "PHASE99_ALIAS": "phase9_9_best",
            "DEFAULT_SEED": 42,
            "train_split_ratio": 0.85,
        },
        "objects_created": [
            "Phase99Bundle",
            "StandardScaler",
            "TrainingModel (logistic via create_regularized_model)",
            "metadata dict",
            "config.json payload (= cfg)",
        ],
    }


def build_default_config_trace() -> dict[str, Any]:
    """STEP 2 + STEP 3 — DEFAULT_CONFIG origin and nature."""
    literal = _parse_default_config_literal()
    imports = [
        {
            "file": "tradingbot/ml/paper/config.py",
            "line": 18,
            "usage": "from tradingbot.ml.paper_trading.model_registry import DEFAULT_CONFIG",
            "effect": "EXPECTED_FEATURES = list(DEFAULT_CONFIG['features']) at import time",
        },
        {
            "file": "tests/test_ml_paper_phase9_10.py",
            "line": 39,
            "usage": "import DEFAULT_CONFIG for paper trading tests",
        },
        {
            "file": "tradingbot/ml/research/phase22v/model_audit.py",
            "line": 328,
            "usage": "fallback: config = dict(bundle.config or DEFAULT_CONFIG)",
        },
    ]
    return {
        "phase": "22AE",
        "defined_in": _rel(MODEL_REGISTRY),
        "definition_line": 38,
        "builder": "None — module-level literal assigned at import",
        "editors": [
            {
                "who": "source code author",
                "mechanism": "direct edit of DEFAULT_CONFIG dict in model_registry.py",
                "runtime_mutation": False,
            },
            {
                "who": "freeze_phase9_9_artifacts caller",
                "mechanism": "optional config= parameter replaces DEFAULT_CONFIG for that call only",
                "runtime_mutation": "call-local copy via dict(config or DEFAULT_CONFIG)",
            },
        ],
        "literal_value": literal,
        "classification": {
            "hardcoded": True,
            "generated": False,
            "cached": False,
            "loaded_from_json": False,
            "loaded_from_metadata": False,
            "loaded_from_cli": False,
            "loaded_from_environment": False,
        },
        "alignment_with_optimizer_grid": {
            "matches_logistic_strong_reg_candidate": True,
            "matches_stable_top3_features": literal.get("features")
            == ["ema50_slope", "candle_direction", "structure_distance"],
            "note": "DEFAULT_CONFIG mirrors one grid cell (logistic C=0.1 + top3 stable features) chosen manually in Phase 9.10 registry, not wired to select_best()",
        },
        "imports": imports,
    }


def build_freeze_parameter_analysis() -> dict[str, Any]:
    """STEP 4 — parameters passed to freeze; ignored vs overridden."""
    callers = [
        {
            "file": "tradingbot/ml/paper_trading/model_registry.py",
            "function": "load_phase9_9_bundle",
            "call": "freeze_phase9_9_artifacts(training_df, base_dir=base_dir, seed=seed)",
            "config_passed": False,
        },
        {
            "file": "tradingbot/ml/integration/kernel_shadow_runner.py",
            "function": "_ensure_artifacts",
            "call": "freeze_phase9_9_artifacts(df, base_dir=base_dir, seed=42)",
            "config_passed": False,
        },
        {
            "file": "tests/test_ml_paper_phase9_10.py",
            "function": "multiple",
            "call": "freeze_phase9_9_artifacts(df, base_dir=tmp[, seed=42])",
            "config_passed": False,
        },
        {
            "file": "tests/test_ml_phase10_1_kernel_bridge.py",
            "function": "setup",
            "config_passed": False,
        },
        {
            "file": "tests/test_ml_phase10_2_live_shadow.py",
            "function": "setup",
            "config_passed": False,
        },
        {
            "file": "tests/test_ml_phase11_paper.py",
            "function": "setup",
            "config_passed": False,
        },
        {
            "file": "tests/test_ml_shadow_phase10.py",
            "function": "setup",
            "config_passed": False,
        },
        {
            "file": "tests/test_ml_phase10_4_monitoring.py",
            "function": "setup",
            "config_passed": False,
        },
    ]
    return {
        "phase": "22AE",
        "parameters": {
            "df": {"used": True, "purpose": "training data for 85% chronological refit"},
            "base_dir": {"used": True, "purpose": "artifact root via phase9_9_* path helpers"},
            "seed": {"used": True, "purpose": "LogisticRegression random_state via create_regularized_model"},
            "config": {
                "used": "only when explicitly passed",
                "default_behavior": "falls back to DEFAULT_CONFIG",
                "callers_passing_config": 0,
            },
        },
        "ignored_when_config_provided": [
            {
                "field": "cfg['model']",
                "reason": "ModelCandidateConfig hardcodes model_name='logistic' regardless of config['model'] value",
                "line": 115,
            },
            {
                "field": "optimizer best_candidate.candidate_id",
                "reason": "Never read; metadata candidate_id always 'logistic_strong_reg'",
                "line": 136,
            },
            {
                "field": "optimizer best experiment_id / feature_subset",
                "reason": "metadata feature_subset always 'stable_top3'",
                "line": 137,
            },
            {
                "field": "walk-forward training protocol",
                "reason": "freeze retrains single 85% slice; optimizer uses run_candidate_grid windows",
            },
        ],
        "always_overridden_by_hardcode": [
            "candidate_id → 'logistic_strong_reg'",
            "model_name → 'logistic' (via ModelCandidateConfig)",
            "feature_subset metadata → 'stable_top3'",
        ],
        "config_can_override": [
            "features list",
            "parameters (e.g. C)",
            "regime / event_filter",
            "buy_threshold / sell_threshold / tp_r / sl_r / risk_pct",
        ],
        "callers": callers,
        "repository_calls_with_config_kwarg": 0,
    }


def build_hardcoded_constants() -> dict[str, Any]:
    """STEP 5 subset — hardcoded freeze decision constants."""
    default_cfg = _parse_default_config_literal()
    return {
        "phase": "22AE",
        "constants": [
            {
                "name": "DEFAULT_CONFIG",
                "location": _rel(MODEL_REGISTRY),
                "line": 38,
                "value": default_cfg,
                "role": "fallback training/threshold config when config=None",
            },
            {
                "name": "candidate_id",
                "location": _rel(MODEL_REGISTRY),
                "lines": [116, 136],
                "value": "logistic_strong_reg",
                "role": "ModelCandidateConfig + metadata; never from optimizer",
            },
            {
                "name": "model_name",
                "location": _rel(MODEL_REGISTRY),
                "line": 117,
                "value": "logistic",
                "role": "forces logistic even if DEFAULT_CONFIG['model'] says LogisticRegression",
            },
            {
                "name": "feature_subset",
                "location": _rel(MODEL_REGISTRY),
                "line": 137,
                "value": "stable_top3",
                "role": "metadata label only; actual features come from cfg['features'] (= DEFAULT_CONFIG top3 list)",
            },
            {
                "name": "DEFAULT_CONFIG['features']",
                "value": default_cfg.get("features"),
                "role": "matches optimizer subset name stable_top3 from feature research, but selected statically",
            },
            {
                "name": "DEFAULT_CONFIG['parameters']",
                "value": default_cfg.get("parameters"),
                "role": "matches logistic_strong_reg hyperparameters C=0.1 from model_regularization grid",
            },
            {
                "name": "train_split_ratio",
                "location": _rel(MODEL_REGISTRY),
                "line": 107,
                "value": 0.85,
                "role": "differs from walk-forward optimizer validation protocol",
            },
        ],
        "logistic_strong_reg_in_optimizer_grid": {
            "file": "tradingbot/ml/research/robustness_optimizer/model_regularization.py",
            "line": 95,
            "description": "Strong L2 logistic C=0.1",
            "note": "Same candidate exists in optimizer grid but freeze does not select it via rank/select_best",
        },
        "stable_top3_in_feature_research": {
            "file": "tradingbot/ml/research/robustness_optimizer/stable_feature_research.py",
            "line": 68,
            "mechanism": "subsets['stable_top3'] = ranked[:3]",
            "note": "freeze metadata copies subset name as literal; features copied into DEFAULT_CONFIG manually",
        },
    }


def build_optimizer_connection(*, base_dir: str | None) -> dict[str, Any]:
    """STEP 6 — can optimizer output reach freeze?"""
    from tradingbot.ml.data.paths import phase9_9_robustness_report_path

    optimizer_src = _read(OPTIMIZER)
    train_src = _read(TRAIN_CLI)
    registry_src = _read(MODEL_REGISTRY)

    report: dict[str, Any] = {}
    report_path = phase9_9_robustness_report_path(base_dir)
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    best = report.get("best_candidate", {})
    broken_edges = [
        {
            "from": "RobustnessOptimizer.run",
            "to": "freeze_phase9_9_artifacts",
            "status": "MISSING",
            "evidence": "optimization_orchestrator.py ends at save_reports(); no import of model_registry freeze",
        },
        {
            "from": "select_best(ranked)",
            "to": "freeze config/candidate",
            "status": "MISSING",
            "evidence": "best dict stored in JSON report only; never passed to freeze",
        },
        {
            "from": "scripts/train_model.py --phase9-9",
            "to": "freeze_phase9_9_artifacts",
            "status": "MISSING",
            "evidence": "train_model.py lines 191-201 return after optimizer.run(); no freeze call",
        },
        {
            "from": "phase9_9_robustness_report.json",
            "to": "freeze candidate selection",
            "status": "PARTIAL_READ_ONLY",
            "evidence": "_load_phase99_score reads robustness_score only; ignores candidate_id/experiment_id",
        },
        {
            "from": "evaluate_acceptance",
            "to": "freeze gate",
            "status": "MISSING",
            "evidence": "acceptance verdict never consulted before freeze (phase 22AB confirmed)",
        },
    ]

    return {
        "phase": "22AE",
        "optimizer_can_reach_freeze": False,
        "exact_path_exists": False,
        "optimizer_pipeline_end": {
            "file": _rel(OPTIMIZER),
            "last_steps": [
                "rank_candidates(experiments)",
                "select_best(ranked)",
                "evaluate_acceptance(best, baseline)",
                "save_reports(...) → JSON under data/ml/reports/",
            ],
            "returns": "RobustnessOptimizationResult (no freeze)",
        },
        "train_cli_end": {
            "file": _rel(TRAIN_CLI),
            "phase9_9_block": "RobustnessOptimizer.run → print JSON → exit",
            "calls_freeze": "freeze_phase9_9_artifacts" not in train_src,
        },
        "freeze_reads_optimizer": {
            "imports_robustness_optimizer": "model_registry imports create_regularized_model only",
            "reads_best_candidate_id": False,
            "reads_experiment_id": False,
            "reads_feature_subset_from_report": False,
            "reads_robustness_score_only": True,
        },
        "broken_edges": broken_edges,
        "current_report_vs_frozen": {
            "report_path": str(report_path),
            "report_best_candidate_id": best.get("candidate_id"),
            "report_experiment_id": best.get("experiment_id"),
            "report_robustness_score": best.get("robustness_score"),
            "frozen_metadata_candidate_id": "logistic_strong_reg",
            "aligned": best.get("candidate_id") == "logistic_strong_reg" if best else None,
        },
        "hypothetical_wiring_gap": "Even if select_best output were passed as config=, freeze would still hardcode candidate_id/model_name unless freeze implementation changed",
    }


def build_repository_references(usage: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """STEP 5 — repository reference index."""
    return {
        "phase": "22AE",
        "search_terms": list(SEARCH_TERMS),
        "hit_counts": {k: len(v) for k, v in usage.items()},
        "references": usage,
        "production_freeze_callers": [
            "tradingbot/ml/integration/kernel_shadow_runner.py (_ensure_artifacts)",
            "tradingbot/ml/paper_trading/model_registry.py (load_phase9_9_bundle build_if_missing)",
        ],
        "optimizer_references_freeze": usage["freeze_phase9_9_artifacts"],
        "optimizer_module_freeze_imports": False,
    }


def determine_root_cause() -> str:
    """STEP 7 — exactly one root cause token."""
    return "MULTIPLE_CAUSES"


def determine_verdict() -> str:
    return determine_root_cause()


def run_investigation(*, base_dir: str | None = None) -> dict[str, Any]:
    usage = _scan_repository()
    freeze_trace = build_freeze_trace()
    default_trace = build_default_config_trace()
    params = build_freeze_parameter_analysis()
    hardcoded = build_hardcoded_constants()
    optimizer_conn = build_optimizer_connection(base_dir=base_dir)
    refs = build_repository_references(usage)

    root_causes = [
        {
            "id": "HARDCODED_CONFIG",
            "applies": True,
            "summary": "freeze_phase9_9_artifacts uses module-level DEFAULT_CONFIG and hardcodes candidate_id/model_name/feature_subset literals",
        },
        {
            "id": "DISCONNECTED_PIPELINE",
            "applies": True,
            "summary": "RobustnessOptimizer and train_model --phase9-9 never invoke freeze; no code passes select_best output",
        },
        {
            "id": "DEFAULT_OVERRIDE",
            "applies": False,
            "summary": "Optional config= exists but zero callers pass optimizer winner; not the active failure mode",
        },
    ]

    return {
        "freeze_trace": freeze_trace,
        "default_config_trace": default_trace,
        "freeze_parameter_analysis": params,
        "hardcoded_constants": hardcoded,
        "optimizer_connection": optimizer_conn,
        "repository_references": refs,
        "root_causes": root_causes,
        "verdict": determine_verdict(),
        "why_logistic_strong_reg_not_optimizer_winner": (
            "Freeze is a separate Phase 9.10 registry function that always trains "
            "ModelCandidateConfig(candidate_id='logistic_strong_reg', model_name='logistic') "
            "using DEFAULT_CONFIG features/parameters on an 85% chronological slice. "
            "It never reads select_best() or best_candidate from the Phase 9.9 optimizer. "
            "The optimizer winner is written to JSON reports only; the training CLI exits "
            "before any freeze call."
        ),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "production_modified": False,
    }
