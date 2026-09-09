"""Phase 1.5.71 — inspect the documentation memory layer (offline, no fixes)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
DOCS_V2 = ROOT / "docs_v2"

CANONICAL_ENTRY = "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"

CORE_CANONICAL = [
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

STALE_RISK = [
    "docs_v2/01_truth/SOURCE_OF_TRUTH.md",
    "docs_v2/01_truth/CURRENT_STATE.md",
    "docs/robot_behavior_audit/strategy_inventory.md",
    "docs/robot_behavior_audit/configuration_truth.md",
]

CODE_REF = re.compile(
    r"`((?:tradingbot|engine|scripts|start|tests)/[^`:\s]+\.py(?:::[A-Za-z0-9_]+)?)`"
)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def run_baseline(*, write_reports: bool = True) -> dict[str, Any]:
    present = [rel for rel in CORE_CANONICAL if (ROOT / rel).is_file()]
    missing = [rel for rel in CORE_CANONICAL if rel not in present]
    entry = _read(CANONICAL_ENTRY)
    entry_true_files: list[str] = []
    last_verified: dict[str, str] = {}
    citations: dict[str, list[str]] = {}
    missing_status: list[str] = []
    for p in DOCS_V2.rglob("*.md"):
        rel = _rel(p)
        text = p.read_text(encoding="utf-8")
        if "Canonical-Entry:** true" in text:
            entry_true_files.append(rel)
        m = re.search(r"Last verified:\s*(\d{4}-\d{2}-\d{2})", text, re.I)
        if m:
            last_verified[rel] = m.group(1)
        if rel in CORE_CANONICAL and "**Status:**" not in text and "- **Status:**" not in text:
            missing_status.append(rel)
        citations[rel] = CODE_REF.findall(text)

    domains_in_entry = {
        "what_robot_is": "Price Action" in entry and "XAUUSD_i" in entry,
        "startup": "START_BOT.bat" in entry,
        "live_path": "MultiEngineRouterRegistry" in entry,
        "config": "PA_PRODUCTION_LOCK" in entry,
        "pa": "evaluate_m5_london_sweep" in entry,
        "risk": "RiskGate.evaluate" in entry and "999" in entry,
        "execution": "Mt5ExecutionAdapter.execute" in entry,
        "data": "NOT PROVEN" in entry,
        "ml": "trend_rf_v41" in entry and "1.0" in entry,
        "research": "tradingbot/ml/research" in entry,
        "unknowns": "UNKNOWN" in entry,
        "contradictions": "london_sweep" in entry,
        "change_control": "DOCUMENTATION_UPDATE_PROTOCOL" in entry,
    }

    payload: dict[str, Any] = {
        "phase": "1.5.71",
        "offline_only": True,
        "questions": {
            "A_entry_sufficient_as_navigation": {
                "kind": "DERIVED FACT",
                "answer": "YES_AS_NAVIGATION",
                "note": (
                    "PROJECT_SOURCE_OF_TRUTH.md covers identity, path, config table, "
                    "ML, unknowns, contradictions, and links. It is long for every-session load "
                    "and lacks an explicit change-class workflow and NEVER-assume list."
                ),
            },
            "B_fresh_model_without_repo": {
                "kind": "DERIVED FACT",
                "answer": "MOSTLY_YES_WITH_CAVEATS",
                "note": (
                    "A model that reads the canonical tree can answer live owner, symbol, TF, "
                    "PA preset, ML off, v41 C/1.0, RiskGate 999, unknowns. It can still be "
                    "misled by superseded-keep files if it ignores banners. Git/operator env "
                    "are UNKNOWN."
                ),
            },
        },
        "C_absent_from_canonical_entry": {
            "kind": "DOCUMENTATION_GAP_OR_BURIED",
            "items": [
                "Compact NEVER-assume / change-class workflow (not in entry)",
                "KillSwitch exit code 2 (in STARTUP_AND_SHUTDOWN, thin in entry)",
                "WPSQF SignalFilter default OFF (CURRENT_RUNTIME_STATE)",
                "_ReliabilityKernel stale-bar freeze (LIVE_RUNTIME_PATH)",
                "PositionProtector default off",
                "Testing domain / which tests prove live contracts",
                "Git working-tree state",
                "Document ownership (who may redefine a fact)",
                "Machine freshness vs code revision",
                "ChatGPT↔Cursor workflow",
            ],
        },
        "D_duplication_risk": {
            "kind": "CONTRADICTION_RISK",
            "items": [
                "Live path restated in PROJECT_SOURCE_OF_TRUTH, CURRENT_RUNTIME_STATE, LIVE_RUNTIME_PATH, STARTUP_AND_SHUTDOWN",
                "PA preset/session in PROJECT_SOURCE_OF_TRUTH, CURRENT_RUNTIME_STATE, PRICE_ACTION_LIVE_SPEC, CONFIGURATION_TRUTH",
                "v41 C/1.0 in PROJECT_SOURCE_OF_TRUTH, ML_SYSTEM_STATE, MODEL_REGISTRY, CALIBRATION_STATE",
                "PA lock / USE_ML_KERNEL in entry + CONFIGURATION_TRUTH + CURRENT_RUNTIME_STATE",
            ],
        },
        "E_weak_citations": {
            "kind": "DERIVED FACT",
            "note": "Many claims cite files; some omit ::symbol (BAT/PS1 hops, strategy count).",
            "entry_code_refs": citations.get(CANONICAL_ENTRY, []),
        },
        "F_stale_misleading": {
            "kind": "HISTORICAL",
            "files": STALE_RISK,
            "note": "Pointer banners exist; bodies still contain 2026-08-22 Adaptive-era claims.",
        },
        "canonical_entry_true_files": entry_true_files,
        "core_present": present,
        "core_missing": missing,
        "last_verified": last_verified,
        "missing_status_on_core": missing_status,
        "domains_in_entry": domains_in_entry,
        "claim_kinds_used": [
            "FACT",
            "DERIVED FACT",
            "ASSUMPTION",
            "UNKNOWN",
            "CONTRADICTION",
            "HISTORICAL",
            "RESEARCH-ONLY",
        ],
    }
    if write_reports:
        out = ROOT / "data" / "ml" / "reports" / "documentation_memory_hardening"
        out.mkdir(parents=True, exist_ok=True)
        (out / "baseline.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        payload["report_path"] = str(out / "baseline.json")
    return payload


if __name__ == "__main__":
    print(json.dumps(run_baseline()["questions"], indent=2))
