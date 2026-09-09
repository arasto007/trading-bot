"""Inventory markdown documentation and write machine-readable classification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SKIP_DIR = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".cursor", "node_modules"}

CANONICAL_ENTRY = "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"

CANONICAL = [
    CANONICAL_ENTRY,
    "docs_v2/01_truth/CURRENT_RUNTIME_STATE.md",
    "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
    "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md",
    "docs_v2/01_truth/DOCUMENTATION_SYSTEM_AUDIT.md",
    "docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md",
    "docs_v2/02_architecture/DATA_FLOW.md",
    "docs_v2/02_architecture/COMPONENT_BOUNDARIES.md",
    "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
    "docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md",
    "docs_v2/03_runtime/EXECUTION_FLOW.md",
    "docs_v2/04_strategy/ACTIVE_STRATEGIES.md",
    "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
    "docs_v2/05_risk/RISKGATE_SPEC.md",
    "docs_v2/05_risk/RISK_AND_EXECUTION_BOUNDARY.md",
    "docs_v2/06_data/DATA_PIPELINE.md",
    "docs_v2/06_data/DATA_CONTRACTS.md",
    "docs_v2/07_ml/ML_SYSTEM_STATE.md",
    "docs_v2/07_ml/MODEL_REGISTRY.md",
    "docs_v2/07_ml/CALIBRATION_STATE.md",
    "docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md",
]

SUPPORTING = [
    "docs_v2/01_truth/FULL_REPOSITORY_SOURCE_OF_TRUTH.md",
    "docs_v2/04_strategy/PA_LIVE_EDGE_AUDIT.md",
    "docs_v2/07_ml/ML_STATUS.md",
    "docs_v2/07_ml/ML_ARCHITECTURE.md",
    "docs_v2/07_ml/V41_DECISION_AUDIT.md",
    "docs_v2/07_ml/V41_CALIBRATION_EVIDENCE.md",
    "docs_v2/07_ml/V41_TREND_REPLAY_EVIDENCE.md",
    "docs_v2/07_ml/V41_COST_ROBUSTNESS_EVIDENCE.md",
    "docs_v2/07_ml/V41_COST_EVIDENCE_AUDIT.md",
    "docs_v2/07_ml/V41_ROBUSTNESS_EVIDENCE.md",
    "docs_v2/08_testing/TESTING.md",
    "docs_v2/09_operations/RUNBOOK.md",
    "docs_v2/09_operations/OBSERVABILITY.md",
    "docs_v2/02_architecture/PIPELINE.md",
    "docs_v2/02_architecture/MODULE_MAP.md",
    "docs_v2/04_strategy/SIGNAL_FLOW.md",
    "docs_v2/05_risk/POSITION_LIFECYCLE.md",
    "docs_v2/_system/DOCUMENTATION_RULES.md",
]

SUPERSEDED_KEEP = [
    "docs_v2/01_truth/SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/CURRENT_STATE.md",
    "docs_v2/01_truth/KNOWN_ISSUES.md",
    "docs_v2/02_architecture/ARCHITECTURE.md",
    "docs_v2/03_runtime/STARTUP.md",
    "docs_v2/03_runtime/LIVE_LOOP.md",
    "docs_v2/03_runtime/CONFIGURATION.md",
    "docs_v2/04_strategy/STRATEGY.md",
    "docs_v2/05_risk/RISK.md",
]

HISTORICAL = [
    "docs/robot_behavior_audit/",
    "docs/ARCHITECTURE_FA.md",
    "docs/ONBOARDING_FA.md",
    "docs/CAPABILITIES.md",
    "docs/WHITEBOARD_FA.md",
    "docs/PROCESSING_MAP.md",
    "docs/PHASE2_",
    "docs/phase",
]


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def _classify(rel: str) -> str:
    if rel == CANONICAL_ENTRY:
        return "CANONICAL_ENTRY"
    if rel in CANONICAL:
        return "CANONICAL"
    if rel in SUPPORTING:
        return "SUPPORTING"
    if rel in SUPERSEDED_KEEP:
        return "SUPERSEDED_KEEP"
    if rel.startswith("docs/robot_behavior_audit/"):
        return "HISTORICAL_STALE"
    if rel.startswith("docs/"):
        return "HISTORICAL"
    if rel.startswith("docs_v2/07_ml/V41_"):
        return "RESEARCH_EVIDENCE"
    if rel.startswith("docs_v2/04_strategy/PA_LIVE"):
        return "RESEARCH_EVIDENCE"
    if rel.startswith("docs_v2/"):
        return "DOCS_V2_OTHER"
    if rel.startswith("tradingbot/ml/research/"):
        return "RESEARCH_INLINE"
    if rel in {"README.md", "AUTONOMOUS_MODE.md", "DEMO_TEST_OVERRIDES.md"}:
        return "ROOT_OPERATOR"
    return "OTHER"


def inventory_markdown() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in ROOT.rglob("*.md"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIR for part in p.parts):
            continue
        rel = _rel(p)
        rows.append({"path": rel, "class": _classify(rel), "bytes": p.stat().st_size})
    rows.sort(key=lambda r: r["path"])
    return rows


def run_documentation_system_audit(*, write_reports: bool = True) -> dict[str, Any]:
    files = inventory_markdown()
    by_class: dict[str, int] = {}
    for row in files:
        by_class[row["class"]] = by_class.get(row["class"], 0) + 1
    payload = {
        "phase": "1.5.62",
        "canonical_entry": CANONICAL_ENTRY,
        "canonical": CANONICAL,
        "supporting": SUPPORTING,
        "superseded_keep": SUPERSEDED_KEEP,
        "historical_prefixes": HISTORICAL,
        "files": files,
        "counts": {"markdown_files": len(files), "by_class": by_class},
        "rules": {
            "do_not_delete_old_docs": True,
            "code_outranks_docs": True,
            "one_canonical_entry": True,
            "do_not_read_dotenv_secrets": True,
        },
    }
    if write_reports:
        out = ROOT / "data" / "ml" / "reports" / "documentation_system_audit"
        out.mkdir(parents=True, exist_ok=True)
        (out / "audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (out / "files.json").write_text(json.dumps(files, indent=2), encoding="utf-8")
        (out / "canonical.json").write_text(
            json.dumps({"entry": CANONICAL_ENTRY, "canonical": CANONICAL}, indent=2),
            encoding="utf-8",
        )
        payload["report_dir"] = str(out)
    return payload


if __name__ == "__main__":
    result = run_documentation_system_audit()
    print(json.dumps({"counts": result["counts"], "entry": result["canonical_entry"]}, indent=2))
