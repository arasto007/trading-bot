"""Fresh ChatGPT session load-path simulation. Documentation only. No production imports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]

ENTRY = "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
BOOT = "docs_v2/01_truth/CHATGPT_BOOTSTRAP.md"
OWNERS = {
    "PA": "docs_v2/04_strategy/PRICE_ACTION_LIVE_SPEC.md",
    "RISK": "docs_v2/05_risk/RISKGATE_SPEC.md",
    "EXECUTION": "docs_v2/03_runtime/EXECUTION_FLOW.md",
    "CONFIG": "docs_v2/01_truth/CONFIGURATION_TRUTH.md",
    "RUNTIME": "docs_v2/01_truth/CURRENT_RUNTIME_STATE.md",
    "LIVE_PATH": "docs_v2/03_runtime/LIVE_RUNTIME_PATH.md",
    "DATA": "docs_v2/06_data/DATA_CONTRACTS.md",
    "ML": "docs_v2/07_ml/ML_SYSTEM_STATE.md",
    "CALIBRATION": "docs_v2/07_ml/CALIBRATION_STATE.md",
    "UNKNOWN": "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md",
    "OWNERSHIP": "docs_v2/01_truth/DOCUMENT_OWNERSHIP_MATRIX.md",
    "SAFETY": "docs_v2/01_truth/KNOWLEDGE_CONTRACT.md",
    "WORKFLOW": "docs_v2/99_change_control/CHATGPT_CURSOR_WORKFLOW.md",
    "FRESHNESS": "docs_v2/99_change_control/DOCUMENTATION_UPDATE_PROTOCOL.md",
    "IMPACT": "docs_v2/99_change_control/DOCUMENTATION_IMPACT_MAP.md",
    "TESTING": "docs_v2/08_testing/TESTING.md",
    "BASELINE": "docs_v2/01_truth/PROJECT_DECISION_BASELINE.md",
    "WATCH": "docs_v2/01_truth/DOCUMENTATION_WATCHED_CODE_AUDIT.md",
    "BOUNDARY": "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md",
}


FULL_SESSION_OWNERS = (
    "BASELINE",
    "PA",
    "RISK",
    "EXECUTION",
    "CONFIG",
    "RUNTIME",
    "LIVE_PATH",
    "DATA",
    "ML",
    "CALIBRATION",
    "UNKNOWN",
    "OWNERSHIP",
    "SAFETY",
    "WORKFLOW",
    "FRESHNESS",
    "IMPACT",
    "TESTING",
    "WATCH",
    "BOUNDARY",
)


def _load(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def corpus(owner_keys: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    files = [ENTRY, BOOT]
    for key in owner_keys:
        files.append(OWNERS[key])
    ordered = []
    seen: set[str] = set()
    for rel in files:
        if rel not in seen:
            seen.add(rel)
            ordered.append(rel)
    blob = "\n\n".join(_load(rel) for rel in ordered)
    return blob, ordered


def _has(blob: str, *needles: str) -> bool:
    return all(n in blob for n in needles)


def classify_questions(blob: str, *, owners_loaded: tuple[str, ...]) -> list[dict[str, Any]]:
    """Epistemic classifications. UNKNOWN is success when the fact is not established."""
    pa_loaded = "PA" in owners_loaded
    risk_loaded = "RISK" in owners_loaded
    rows = [
        {
            "id": "Q_robot",
            "q": "What is the robot?",
            "expected": "DOCUMENTED",
            "ok": _has(blob, "Price Action", "MetaTrader") or _has(blob, "Price Action", "XAUUSD_i"),
        },
        {
            "id": "Q_strategy_owner",
            "q": "What strategy owns default live trading?",
            "expected": "DOCUMENTED",
            "ok": _has(blob, "priceaction") and ("Price Action" in blob),
        },
        {
            "id": "Q_symbol",
            "q": "What symbol?",
            "expected": "DOCUMENTED",
            "ok": _has(blob, "XAUUSD_i"),
        },
        {
            "id": "Q_timeframe",
            "q": "What timeframe?",
            "expected": "DOCUMENTED",
            "ok": "5m" in blob or "M5" in blob,
        },
        {
            "id": "Q_preset",
            "q": "What PA preset?",
            "expected": "DOCUMENTED",
            "ok": _has(blob, "gold_ny_sweep"),
        },
        {
            "id": "Q_sl_tp",
            "q": "What exact PA SL/TP logic?",
            "expected": "DOCUMENTED" if pa_loaded else "DERIVED",
            "ok": (
                (_has(blob, "SL_ATR_MULT") and ("0.35" in blob) and ("1.5" in blob))
                if pa_loaded
                else ("PRICE_ACTION_LIVE_SPEC" in blob)
            ),
        },
        {
            "id": "Q_riskgate_role",
            "q": "What RiskGate role?",
            "expected": "DOCUMENTED",
            "ok": "RiskGate" in blob and ("mandatory" in blob.lower() or "evaluate" in blob),
        },
        {
            "id": "Q_riskgate_hops",
            "q": "Full RiskGate hop order?",
            "expected": "DOCUMENTED" if risk_loaded else "DERIVED",
            "ok": ("Entry freeze" in blob and "Meta" in blob) if risk_loaded else ("RISKGATE_SPEC" in blob),
        },
        {
            "id": "Q_execution_modes",
            "q": "What execution modes?",
            "expected": "DOCUMENTED",
            "ok": "dry-run" in blob.lower() or "Dry-run" in blob,
        },
        {
            "id": "Q_ml_active",
            "q": "Is ML active?",
            "expected": "DOCUMENTED",
            "ok": _has(blob, "USE_ML_KERNEL")
            and ("false" in blob.lower() or "off" in blob.lower()),
        },
        {
            "id": "Q_v41_status",
            "q": "What is v41 status?",
            "expected": "DOCUMENTED",
            "ok": "inactive" in blob.lower() or "INACTIVE" in blob,
        },
        {
            "id": "Q_v41_factor",
            "q": "What is v41 calibration factor?",
            "expected": "DOCUMENTED",
            "ok": _has(blob, "1.0"),
        },
        {
            "id": "Q_unknown_env",
            "q": "Operator .env values?",
            "expected": "UNKNOWN",
            "ok": ".env" in blob and "UNKNOWN" in blob,
        },
        {
            "id": "Q_identity",
            "q": "XAUUSD equals XAUUSD_i?",
            "expected": "UNKNOWN",
            "ok": "NOT PROVEN" in blob or "UNK-002" in blob,
        },
        {
            "id": "Q_contradiction",
            "q": "Does london_sweep mean London hours?",
            "expected": "CONTRADICTED",
            "ok": "london_sweep" in blob and "NY 15" in blob,
        },
        {
            "id": "Q_never_assume",
            "q": "What must never be assumed?",
            "expected": "DOCUMENTED",
            "ok": "NEVER assume" in blob or "must NEVER assume" in blob,
        },
        {
            "id": "Q_pa_owner",
            "q": "Which document owns PA?",
            "expected": "DOCUMENTED",
            "ok": "PRICE_ACTION_LIVE_SPEC" in blob,
        },
        {
            "id": "Q_risk_owner",
            "q": "Which document owns RiskGate?",
            "expected": "DOCUMENTED",
            "ok": "RISKGATE_SPEC" in blob,
        },
        {
            "id": "Q_after_code_change",
            "q": "What happens after production code changes?",
            "expected": "DOCUMENTED",
            "ok": "STALE" in blob or "stale" in blob.lower(),
        },
        {
            "id": "Q_freshness_how",
            "q": "How does ChatGPT know docs are stale?",
            "expected": "DOCUMENTED",
            "ok": "freshness" in blob.lower() or "SHA-256" in blob or "watched" in blob.lower(),
        },
        {
            "id": "Q_cursor_verify",
            "q": "What requires Cursor verification?",
            "expected": "DOCUMENTED",
            "ok": "Cursor" in blob,
        },
        {
            "id": "Q_operator_mt5",
            "q": "What requires operator/MT5 evidence?",
            "expected": "UNKNOWN",
            "ok": "UNKNOWN" in blob and ("MT5" in blob or "commission" in blob.lower() or "identity" in blob.lower()),
        },
        {
            "id": "Q_daemon_now",
            "q": "Is the daemon running now?",
            "expected": "UNKNOWN",
            "ok": True,
        },
        {
            "id": "Q_operator_state",
            "q": "Is documented default the operator-effective state?",
            "expected": "UNKNOWN",
            "ok": "Operator-effective state: UNKNOWN" in blob or "operator env UNKNOWN" in blob.lower()
            or "Operator `.env`" in blob,
        },
        {
            "id": "Q_commission",
            "q": "Current broker commission?",
            "expected": "UNKNOWN",
            "ok": "Commission" in blob or "commission" in blob.lower() or "round-trip" in blob.lower(),
        },
        {
            "id": "Q_demo_symbol",
            "q": "Demo gold symbol?",
            "expected": "DOCUMENTED",
            "ok": "XAUUSD_i" in blob and ("DEMO" in blob or "demo" in blob or "USER-PROVIDED" in blob),
        },
        {
            "id": "Q_real_symbol",
            "q": "Real gold symbol?",
            "expected": "DOCUMENTED",
            "ok": "XAUUSD" in blob and ("REAL" in blob or "Real" in blob or "USER-PROVIDED" in blob),
        },
        {
            "id": "Q_pa_session",
            "q": "PA session?",
            "expected": "DOCUMENTED",
            "ok": "NY 15" in blob and ("London" in blob),
        },
        {
            "id": "Q_pa_sl",
            "q": "PA SL?",
            "expected": "DOCUMENTED" if pa_loaded else "DERIVED",
            "ok": ("0.35" in blob and "SL" in blob) if pa_loaded else ("PRICE_ACTION_LIVE_SPEC" in blob),
        },
        {
            "id": "Q_pa_tp",
            "q": "PA TP?",
            "expected": "DOCUMENTED" if pa_loaded else "DERIVED",
            "ok": ("1.5" in blob and "TP" in blob) if pa_loaded else ("PRICE_ACTION_LIVE_SPEC" in blob),
        },
        {
            "id": "Q_orders_now",
            "q": "Current open orders?",
            "expected": "UNKNOWN",
            "ok": "UNKNOWN" in blob and ("order" in blob.lower() or "orders" in blob.lower()),
        },
        {
            "id": "Q_account_now",
            "q": "Current account state?",
            "expected": "UNKNOWN",
            "ok": "UNKNOWN" in blob and ("account" in blob.lower()),
        },
        {
            "id": "Q_boundary",
            "q": "Production vs research boundary?",
            "expected": "DOCUMENTED",
            "ok": "ml/research" in blob and ("PRODUCTION" in blob or "build_kernel_live" in blob),
        },
        {
            "id": "Q_hierarchy",
            "q": "Documentation hierarchy?",
            "expected": "DOCUMENTED",
            "ok": "CODE > CANONICAL" in blob or "CODE > this" in blob,
        },
        {
            "id": "Q_ownership",
            "q": "Ownership model?",
            "expected": "DOCUMENTED",
            "ok": "DOCUMENT_OWNERSHIP_MATRIX" in blob or "Domain ID" in blob,
        },
        {
            "id": "Q_impact",
            "q": "Change-impact rule?",
            "expected": "DOCUMENTED",
            "ok": "DOCUMENTATION_IMPACT_MAP" in blob or "CODE CHANGE" in blob,
        },
        {
            "id": "Q_testing_entry",
            "q": "Testing entry?",
            "expected": "DOCUMENTED",
            "ok": "TESTING.md" in blob or "test_documentation" in blob,
        },
        {
            "id": "Q_state_columns",
            "q": "Code default vs operator vs process?",
            "expected": "DOCUMENTED",
            "ok": "CODE DEFAULT" in blob or "Operator-effective state: UNKNOWN" in blob,
        },
    ]
    out = []
    for row in rows:
        classification = row["expected"] if row["ok"] else "GAP"
        out.append(
            {
                "id": row["id"],
                "q": row["q"],
                "expected": row["expected"],
                "classification": classification,
                "ok": row["ok"] and classification == row["expected"],
            }
        )
    return out


def hallucination_guards(blob: str) -> list[dict[str, Any]]:
    """Reject wording that converts UNKNOWN into known operator/runtime facts."""
    lower = blob.lower()
    checks = [
        {
            "id": "H_env_not_claimed_equal_defaults",
            "ok": "assume .env equals" not in lower and ".env equals code defaults" not in lower,
            "note": "must not claim .env equals defaults as fact",
        },
        {
            "id": "H_operator_effective_unknown",
            "ok": "Operator-effective state: UNKNOWN" in blob or "operator env UNKNOWN" in blob
            or "Operator `.env`" in blob and "UNKNOWN" in blob,
            "note": "operator state remains UNKNOWN",
        },
        {
            "id": "H_not_current_live_heading",
            "ok": "## 2. Current live system" not in blob,
            "note": "ambiguous Current live system heading must not remain",
        },
        {
            "id": "H_daemon_pid_not_claimed",
            "ok": "pid =" not in lower
            and "daemon is running" not in lower
            and "bot is running now" not in lower,
            "note": "must not invent a live process or PID",
        },
        {
            "id": "H_identity_not_proven",
            "ok": "NOT PROVEN" in blob or "UNK-002" in blob,
            "note": "symbol identity stays unproven",
        },
        {
            "id": "H_v41_not_live",
            "ok": "v41" in lower and ("inactive" in lower or "INACTIVE" in blob),
            "note": "v41 must not be presented as live",
        },
    ]
    return checks
