"""Documentation memory hardening v2 runner. Docs/research/tests only. No production imports."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

from tradingbot.ml.research.documentation_freshness.scanner import WATCHED
from tradingbot.ml.research.documentation_memory_hardening_v2.load_path import (
    FULL_SESSION_OWNERS,
    classify_questions,
    corpus,
    hallucination_guards,
)

REPORT_DIR = ROOT / "data" / "ml" / "reports" / "documentation_memory_hardening_v2"

REQUIRED_OWNERS = {
    "PROJECT_IDENTITY": "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md",
    "SESSION_LOAD": "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md",
    "LIVE_CONTRACT": "docs_v2/01_truth/CURRENT_RUNTIME_STATE.md",
    "LIVE_PATH": "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
    "CONFIGURATION": "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "ARCHITECTURE": "docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md",
    "PA_STRATEGY": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
    "STRATEGY_LIST": "docs_v2/04_strategy/ACTIVE_STRATEGIES.md",
    "RISKGATE": "docs_v2/05_risk/RISKGATE_SPEC.md",
    "EXECUTION": "docs_v2/03_runtime/EXECUTION_FLOW.md",
    "DATA_CONTRACTS": "docs_v2/06_data/DATA_CONTRACTS.md",
    "ML": "docs_v2/07_ml/ML_SYSTEM_STATE.md",
    "CALIBRATION": "docs_v2/07_ml/CALIBRATION_STATE.md",
    "PRODUCTION_BOUNDARY": "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md",
    "UNKNOWNS_CONTRADICTIONS": "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
    "SAFETY_INVARIANTS": "docs_v2/01_truth/KNOWLEDGE_CONTRACT.md",
    "CHANGE_CONTROL": "docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md",
    "IMPACT_MAP": "docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md",
    "HANDOFF": "docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md",
    "FRESHNESS": "docs_v2/01_truth/DOCUMENTATION_WATCHED_CODE_AUDIT.md",
    "TESTING": "docs_v2/08_testing/TESTING.md",
}

WATCH_CLASSIFICATIONS: list[dict[str, Any]] = [
    {
        "path": "tradingbot/ml/confidence_engine/calibration_policy.py",
        "decision": "WATCH",
        "reason": "Calibration constants consumed on ML path; listed on impact map; can change v41/v40 factor bounds.",
        "domain": "CALIBRATION",
        "owner": "docs_v2/07_ml/CALIBRATION_STATE.md",
        "safety": "PRODUCTION-SENSITIVE",
    },
    {
        "path": "tradingbot/domain/gold_strategies/router.py",
        "decision": "WATCH",
        "reason": "evaluate_gold_setup is the live PA dispatcher to evaluate_m5_london_sweep.",
        "domain": "PA_STRATEGY",
        "owner": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "tradingbot/domain/pa_hardening.py",
        "decision": "WATCH",
        "reason": "apply_setup_hardening can return None and mutate quality after the sweep evaluator.",
        "domain": "PA_STRATEGY",
        "owner": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "tradingbot/pipeline/signal_stage.py",
        "decision": "WATCH",
        "reason": "SignalStage.run is the call site of exclude_forming_bar on the live kernel path.",
        "domain": "LIVE_PATH",
        "owner": "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "tradingbot/__main__.py",
        "decision": "WATCH",
        "reason": "CLI --loop --execute and --tf default M15 vs daemon live M5 (CX-015).",
        "domain": "LIVE_PATH",
        "owner": "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "start/START_BOT.bat",
        "decision": "WATCH",
        "reason": "Documented default Windows start of the live chain.",
        "domain": "LIVE_PATH",
        "owner": "docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "start/_load_env.bat",
        "decision": "WATCH",
        "reason": "Loads operator .env into cmd before start_bot; changes configuration precedence. Values remain UNKNOWN.",
        "domain": "CONFIGURATION",
        "owner": "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
        "safety": "PRODUCTION-SENSITIVE",
    },
    {
        "path": "tradingbot/ml/risk_intelligence/risk_types.py",
        "decision": "WATCH",
        "reason": "factory imports AccountState/HistoricalMetrics; engine_quality_factor keys trend_rf_v40 only.",
        "domain": "CALIBRATION",
        "owner": "docs_v2/07_ml/CALIBRATION_STATE.md",
        "safety": "PRODUCTION-SENSITIVE",
    },
    {
        "path": "tradingbot/adapters/mt5_market_data.py",
        "decision": "WATCH",
        "reason": "Live bar source for DataStage / MT5 rates; data-contract identity.",
        "domain": "DATA_CONTRACTS",
        "owner": "docs_v2/06_data/DATA_CONTRACTS.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "tradingbot/adapters/legacy_strategy_registry.py",
        "decision": "WATCH",
        "reason": "Live hop: router → LegacyStrategyRegistry → PriceActionStrategy.",
        "domain": "LIVE_PATH",
        "owner": "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
        "safety": "PRODUCTION-CRITICAL",
    },
    {
        "path": "tradingbot/services/kill_switch.py",
        "decision": "WATCH",
        "reason": "Documented live hop 21; process abort can stop live loop.",
        "domain": "LIVE_PATH",
        "owner": "docs_v2/03_runtime/STARTUP_AND_SHUTDOWN.md",
        "safety": "PRODUCTION-SENSITIVE",
    },
    {
        "path": "tradingbot/config/engine_settings.py",
        "decision": "WATCH",
        "reason": "Cited credential fallbacks (CX-016). File is hashed; secret values are not documented.",
        "domain": "CONFIGURATION",
        "owner": "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
        "safety": "PRODUCTION-SENSITIVE",
    },
    {
        "path": "tradingbot/domain/gold_strategies/m5_scalp.py",
        "decision": "DO_NOT_WATCH",
        "reason": "Not selected when GOLD_STRATEGY_MODE resolves to london_sweep. Dispatch lives in watched router.py.",
        "domain": "PA_STRATEGY",
        "owner": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
        "safety": "UNUSED-ON-DEFAULT-LIVE",
    },
    {
        "path": "tradingbot/domain/gold_strategies/m15_intraday.py",
        "decision": "DO_NOT_WATCH",
        "reason": "Not selected on default live M5 london_sweep path.",
        "domain": "PA_STRATEGY",
        "owner": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
        "safety": "UNUSED-ON-DEFAULT-LIVE",
    },
    {
        "path": "tradingbot/domain/gold_strategies/h4_swing.py",
        "decision": "DO_NOT_WATCH",
        "reason": "Not selected on default live M5 london_sweep path.",
        "domain": "PA_STRATEGY",
        "owner": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
        "safety": "UNUSED-ON-DEFAULT-LIVE",
    },
    {
        "path": "tradingbot/ml/research/documentation_freshness/scanner.py",
        "decision": "RESEARCH_ONLY",
        "reason": "Verifier, not live runtime. Watching it would couple docs tooling to itself.",
        "domain": "CHANGE_CONTROL",
        "owner": "docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md",
        "safety": "RESEARCH",
    },
    {
        "path": "tradingbot/ml/research/**",
        "decision": "RESEARCH_ONLY",
        "reason": "Must not enter build_kernel_live.",
        "domain": "PRODUCTION_BOUNDARY",
        "owner": "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md",
        "safety": "RESEARCH",
    },
    {
        "path": "complete production call graph",
        "decision": "UNKNOWN",
        "reason": "No complete static graph. Remaining files may exist that can affect live behavior.",
        "domain": "LIVE_PATH",
        "owner": "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
        "safety": "UNKNOWN",
    },
]


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def bootstrap_imports_research() -> bool:
    text = _read("tradingbot/application/bootstrap.py")
    return "ml.research" in text or "documentation_freshness" in text or "documentation_consistency" in text


def unique_canonical_entry() -> list[str]:
    found = []
    for p in (ROOT / "docs_v2").rglob("*.md"):
        if "Canonical-Entry:** true" in p.read_text(encoding="utf-8"):
            found.append(p.relative_to(ROOT).as_posix())
    return found


def ownership_audit() -> dict[str, Any]:
    matrix = _read("docs_v2/01_truth/DOCUMENT_OWNERSHIP_MATRIX.md")
    missing = []
    duplicate_mentions = []
    for domain, owner in REQUIRED_OWNERS.items():
        if domain not in matrix:
            missing.append(domain)
        if owner.split("/")[-1] not in matrix:
            missing.append(owner)
    owners = list(REQUIRED_OWNERS.values())
    counts = Counter(owners)
    duplicates = [o for o, n in counts.items() if n > 1]
    return {
        "required": REQUIRED_OWNERS,
        "missing_from_matrix": missing,
        "duplicate_owner_paths": duplicates,
        "ok": not missing and not duplicates,
    }


def impact_map_audit() -> dict[str, Any]:
    impact = _read("docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md")
    missing_from_map = [rel for rel in WATCHED if f"`{rel}`" not in impact]
    derived_required = [
        "PROJECT_SOURCE_OF_TRUTH.md",
        "CHATGPT_BOOTSTRAP.md",
    ]
    missing_derived_column = [name for name in derived_required if name not in impact]
    return {
        "watched_not_in_impact_map": missing_from_map,
        "derived_docs_named": missing_derived_column == [],
        "ok": not missing_from_map and not missing_derived_column,
    }


def run_hardening_v2(*, write_reports: bool = True) -> dict[str, Any]:
    blob, files = corpus(FULL_SESSION_OWNERS)
    questions = classify_questions(blob, owners_loaded=FULL_SESSION_OWNERS)
    guards = hallucination_guards(blob)
    owner = ownership_audit()
    impact = impact_map_audit()
    entries = unique_canonical_entry()
    watch_must = [row["path"] for row in WATCH_CLASSIFICATIONS if row["decision"] == "WATCH"]
    watch_missing = [p for p in watch_must if p not in WATCHED]
    payload = {
        "phase": "documentation_memory_hardening_v2",
        "offline_only": True,
        "production_source_read": False,
        "session_files": files,
        "canonical_entry_files": entries,
        "canonical_entry_count": len(entries),
        "watched_count": len(WATCHED),
        "watch_classifications": WATCH_CLASSIFICATIONS,
        "required_watch_missing_from_WATCHED": watch_missing,
        "bootstrap_imports_research": bootstrap_imports_research(),
        "ownership": owner,
        "impact_map": impact,
        "questions": questions,
        "question_failures": [q for q in questions if not q["ok"]],
        "hallucination_guards": guards,
        "hallucination_failures": [g for g in guards if not g["ok"]],
        "ok": (
            len(entries) == 1
            and not watch_missing
            and owner["ok"]
            and impact["ok"]
            and not any(not q["ok"] for q in questions)
            and not any(not g["ok"] for g in guards)
            and bootstrap_imports_research() is False
        ),
    }
    if write_reports:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "verification.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        (REPORT_DIR / "watched_code_audit.json").write_text(
            json.dumps(
                {
                    "watched": WATCHED,
                    "classifications": WATCH_CLASSIFICATIONS,
                    "required_watch_missing_from_WATCHED": watch_missing,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return payload


if __name__ == "__main__":
    result = run_hardening_v2()
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "canonical_entry_count": result["canonical_entry_count"],
                "watched_count": result["watched_count"],
                "question_failures": result["question_failures"],
                "hallucination_failures": result["hallucination_failures"],
                "watch_missing": result["required_watch_missing_from_WATCHED"],
                "ownership_missing": result["ownership"]["missing_from_matrix"],
                "impact_missing": result["impact_map"]["watched_not_in_impact_map"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["ok"] else 1)
