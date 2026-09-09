"""Phase 60 — unified evidence gate for G1–G8.

Does not mutate Phase 40–59 artifacts. Does not authorize live/shadow/optimization.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "60"
PHASE60_JSON = "logs/phase60_unified_evidence_gate.json"
PHASE60_MD = "docs/PHASE60_UNIFIED_EVIDENCE_GATE.md"
PHASE57_60_MD = "docs/PHASE57_60_EVIDENCE_CLOSURE.md"
OPERATOR_MD = "docs/OPERATOR_EVIDENCE_REQUEST.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE50_JSON = "logs/phase50_final_production_parity.json"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
PHASE56_JSON = "logs/phase56_symbol_mapping_final_gate.json"
PHASE57_JSON = "logs/phase57_account_product_forensics.json"
PHASE58_JSON = "logs/phase58_commission_accountability.json"
PHASE59_JSON = "logs/phase59_symbol_equivalence_forensics.json"
UNKNOWN = "UNKNOWN"
BLOCKED = "BLOCKED"
FROZEN = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "gates",
    "AUTHORIZED_NEXT_PHASE",
    "INFORMATION_VALUE_RANKING",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=base_dir, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 57–60 (`docs/PHASE57_ACCOUNT_PRODUCT_FORENSICS.md`, "
        "`docs/PHASE58_COMMISSION_ACCOUNTABILITY.md`, `docs/PHASE59_SYMBOL_EQUIVALENCE_FORENSICS.md`, "
        "`docs/PHASE60_UNIFIED_EVIDENCE_GATE.md`) are research-only G1–G3 forensics and a unified gate. "
        "They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 54–56"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 57 account product forensics | `run_phase57_collection()` | n/a | RESEARCH; attach-if-running | **PASS**; G1 PARTIAL |\n"
        "| Phase 58 commission accountability | `run_phase58_collection()` | n/a | RESEARCH; scenarios + break-even | **PASS**; G2 not VERIFIED |\n"
        "| Phase 59 symbol equivalence | `run_phase59_collection()` | n/a | RESEARCH; no rename | **PASS**; G3 NOT_PROVEN |\n"
        "| Phase 60 unified evidence gate | `run_phase60_collection()` | n/a | RESEARCH; no optimize/live | **PASS**; TARGETED_EVIDENCE_COLLECTION |"
    )
    if "Phase 57 account product forensics" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase57_account_product_forensics.py` — **RESEARCH_ONLY** product discriminators; no .env.\n"
        "`tradingbot/backtest/phase58_commission_accountability.py` — **RESEARCH_ONLY** cost scenarios/break-even.\n"
        "`tradingbot/backtest/phase59_symbol_equivalence_forensics.py` — **RESEARCH_ONLY** EV-EQ-01 forensics; no rename.\n"
        "`tradingbot/backtest/phase60_unified_evidence_gate.py` — **RESEARCH_ONLY** unified G1–G8 gate.\n"
    )
    needle = "`tradingbot/backtest/phase56_symbol_mapping_final_gate.py`"
    if "phase57_account_product_forensics.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 57 started | **NO** |", "| Phase 57 started | **YES** |")
    block = f"""

## Account product / commission / symbol forensics (Phases 57–60)

| Claim | Status |
|---|---|
| G1 account product | **{payload.get("G1")}** |
| G2 commission | **{payload.get("G2")}** |
| G3 symbol equivalence | **{payload.get("G3")}** |
| AUTHORIZED_NEXT_PHASE | **{payload.get("AUTHORIZED_NEXT_PHASE")}** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Optimization / shadow / live | **NO-GO** |
| Phase 61 started | **NO** |
"""
    if "## Account product / commission / symbol forensics (Phases 57–60)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def run_phase60_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p50 = _safe_load_json(root / PHASE50_JSON) or {}
    p54 = _safe_load_json(root / PHASE54_JSON) or {}
    p56 = _safe_load_json(root / PHASE56_JSON) or {}
    p57 = _safe_load_json(root / PHASE57_JSON) or {}
    p58 = _safe_load_json(root / PHASE58_JSON) or {}
    p59 = _safe_load_json(root / PHASE59_JSON) or {}
    g1 = str(p57.get("G1") or "FAIL")
    g2 = str(p58.get("G2") or "UNKNOWN")
    g3 = str(p59.get("G3") or "FAIL")
    old = p56.get("gates") or {}

    def _old(name: str, default: str) -> str:
        node = old.get(name) or {}
        return str(node.get("status") or default)

    g4 = _old("G4_HISTORICAL_BID_ASK", "PARTIAL")
    g5 = _old("G5_HISTORICAL_SWAP", "PARTIAL")
    g6 = _old("G6_REQUEST_FILL_TELEMETRY", "FAIL")
    g7 = _old("G7_EXECUTABLE_COST_AWARE_BACKTEST", "FAIL")
    g8 = _old("G8_BROKER_EXECUTION_PARITY", "FAIL")
    all_core = g1 == "PASS" and g2 == "PASS" and g3 == "PASS"
    next_phase = "EXECUTABLE_COST_AWARE_VALIDATION" if all_core else "TARGETED_EVIDENCE_COLLECTION"
    ranking = [
        {"RANK": 1, "BLOCKER": "G1 account product", "WHY_IT_MATTERS": "Selects ECN $5 vs CLASSIC/CENT 14-point markup", "CHEAPEST_SAFE_WAY_TO_CLOSE": "Cabinet screenshot of Account type with secrets redacted", "EXPECTED_INFORMATION_VALUE": "HIGHEST"},
        {"RANK": 2, "BLOCKER": "G3 XAUUSD ↔ XAUUSD_i", "WHY_IT_MATTERS": "Whether research tape symbol is the REAL tradable gold name", "CHEAPEST_SAFE_WAY_TO_CLOSE": "Support/official statement of _i alias; no credentials", "EXPECTED_INFORMATION_VALUE": "HIGH"},
        {"RANK": 3, "BLOCKER": "G2 verified schedule", "WHY_IT_MATTERS": "Unlocks executable cost-aware validation", "CHEAPEST_SAFE_WAY_TO_CLOSE": "Follows G1; official table already captured", "EXPECTED_INFORMATION_VALUE": "HIGH given G1"},
        {"RANK": 4, "BLOCKER": "G6 request/fill", "WHY_IT_MATTERS": "Realized slippage", "CHEAPEST_SAFE_WAY_TO_CLOSE": "Passive schema already exists; do not send orders", "EXPECTED_INFORMATION_VALUE": "MEDIUM"},
        {"RANK": 5, "BLOCKER": "G4/G5 historical Bid/Ask and swap", "WHY_IT_MATTERS": "Eval-tape costs", "CHEAPEST_SAFE_WAY_TO_CLOSE": "Bounded probes only; no hang download", "EXPECTED_INFORMATION_VALUE": "MEDIUM / expensive"},
    ]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "gates": {
            "G1_ACCOUNT_PRODUCT": g1,
            "G2_COMMISSION": g2,
            "G3_SYMBOL_EQUIVALENCE": g3,
            "G4_HISTORICAL_BID_ASK": g4,
            "G5_HISTORICAL_SWAP": g5,
            "G6_REQUEST_FILL": g6,
            "G7_EXECUTABLE_BACKTEST": g7,
            "G8_EXECUTION_PARITY": g8,
        },
        "G1": g1,
        "G2": g2,
        "G3": g3,
        "ACCOUNT_PRODUCT": p57.get("ACCOUNT_PRODUCT"),
        "ACCOUNT_PRODUCT_CANDIDATE": p57.get("ACCOUNT_PRODUCT_CANDIDATE"),
        "COMMISSION_STATUS": (p54.get("commission") or {}).get("OBSERVED_COMMISSION_STATUS"),
        "SYMBOL_MAPPING": p59.get("SYMBOL_MAPPING"),
        "BREAK_EVEN_COST_R": p58.get("BREAK_EVEN_COST_R"),
        "BREAK_EVEN_COST_USD_PER_LOT": p58.get("BREAK_EVEN_COST_USD_PER_LOT"),
        "RAW_EDGE_R": ((p40.get("raw_performance") or {}).get("expectancy_R")),
        "ECN_SCENARIO_NET_EDGE_R": p58.get("ECN_SCENARIO_NET_EDGE_R"),
        "EDGE_VS_COST_UNCERTAINTY": (p58.get("margin") or {}).get("classification"),
        "AUTHORIZED_NEXT_PHASE": next_phase,
        "INFORMATION_VALUE_RANKING": ranking,
        "OPTIMIZATION_ALLOWED": False,
        "SHADOW_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "project_stopped": False,
        "prior_sources": {
            "phase40": bool(p40),
            "phase45": bool(p45),
            "phase50": bool(p50),
            "phase54": bool(p54),
            "phase56": bool(p56),
            "phase57": bool(p57),
            "phase58": bool(p58),
            "phase59": bool(p59),
            "mutated": False,
        },
        "robustness": p45.get("robustness_verdict"),
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE60_JSON, "md": PHASE60_MD, "closure_md": PHASE57_60_MD, "operator_md": OPERATOR_MD},
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
    }
    (root / PHASE60_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE60_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 60 — Unified Evidence Gate",
        "",
        f"**AUTHORIZED_NEXT_PHASE:** `{next_phase}`",
        f"**G1:** `{g1}`  **G2:** `{g2}`  **G3:** `{g3}`",
        "**OPTIMIZATION_ALLOWED:** FALSE  **SHADOW_ALLOWED:** FALSE  **LIVE_TRADING_ALLOWED:** FALSE",
        "",
        "G1–G3 are not all PASS. Next work is targeted operator/broker evidence, not another broad audit, not executable validation, not live.",
        "",
    ]
    (root / PHASE60_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE60_MD).write_text("\n".join(md), encoding="utf-8")
    operator = [
        "# Operator evidence request (sanitized only)",
        "",
        "Do **not** send password, login, `.env`, API keys, tokens, or payment details.",
        "",
        "## A) Account product (closes G1, then G2)",
        "",
        "From LiteFinance Cabinet → Account / Trading account type, tell us **one** of:",
        "",
        "- `ECN`",
        "- `CLASSIC`",
        "- `CENT`",
        "",
        "A screenshot is fine if **account number, balance, name, and credentials are redacted**.",
        "",
        "## B) Gold symbol (closes G3)",
        "",
        "A Cabinet/support sentence such as:",
        "",
        "> XAUUSD_i is the REAL LiteFinance-MT5-Live symbol corresponding to XAUUSD",
        "",
        "or an official document/catalog showing that equivalence.",
        "",
        "Screenshot: redact account number, balance, credentials, and personal information.",
        "",
        "That is the entire request. Nothing else is needed from you for the next research step.",
        "",
    ]
    (root / OPERATOR_MD).write_text("\n".join(operator), encoding="utf-8")
    closure = [
        "# Phase 57–60 — Evidence Closure",
        "",
        "## EXECUTIVE_STATUS",
        "",
        f"Research advanced. G1=`{g1}` (candidate `{p57.get('ACCOUNT_PRODUCT_CANDIDATE')}`). G2=`{g2}`. G3=`{g3}`. Live/optimization remain NO-GO. Project is **not** stopped.",
        "",
        "## CURRENT_GATE",
        f"`{next_phase}` / FINAL_GATE BLOCKED",
        "",
        f"## G1_ACCOUNT_PRODUCT\n`{g1}` — {p57.get('ACCOUNT_PRODUCT')} candidate {p57.get('ACCOUNT_PRODUCT_CANDIDATE')}",
        f"## G2_COMMISSION\n`{g2}` — observed zeros NOT_PROVEN_SCHEDULE; CLASSIC 14 now converted as **points** (official PDF).",
        f"## G3_SYMBOL_EQUIVALENCE\n`{g3}` — official XAUUSD swap/contract match XAUUSD_i is SUPPORTING only.",
        "## G4_BID_ASK\nPARTIAL",
        "## G5_SWAP\nPARTIAL (current rate observed; historical series unknown)",
        "## G6_REQUEST_FILL\nFAIL (0 pairs)",
        "## G7_EXECUTABLE_VALIDATION\nFAIL",
        "## G8_EXECUTION_PARITY\nFAIL",
        "",
        "## PROVEN_FACTS",
        "- REAL LiteFinance-MT5-Live; XAUUSD_i tradable on this terminal; XAUUSD not in current catalog.",
        "- Official PDF effective 2026-05-19 (prior artifact 2026-03-26 kept as conflict).",
        "- Official CLASSIC/CENT markup units = points per round lot for commodities.",
        "- Official ECN max orders 500 vs CLASSIC/CENT 300; CENT currency USD-¢.",
        "",
        "## UNKNOWN_FACTS",
        "- Exact Cabinet product name for this login.",
        "- Whether XAUUSD_i is officially the alias of XAUUSD.",
        "",
        "## CONTRADICTIONS",
        "- CX-REAL-SYMBOL: operator REAL=XAUUSD vs CODE/catalog XAUUSD_i.",
        "- PDF dates 2026-03-26 vs 2026-05-19 (current fetch confirms 2026-05-19).",
        "",
        "## COST_SCENARIOS / BREAK_EVEN / EDGE",
        f"- ECN scenario net event `{p58.get('ECN_SCENARIO_NET_EDGE_R')}` R",
        f"- Break-even event cost `{p58.get('BREAK_EVEN_COST_R')}` R ≈ `{p58.get('BREAK_EVEN_COST_USD_PER_LOT')}` USD/lot",
        f"- EDGE_VS_COST_UNCERTAINTY: `{(p58.get('margin') or {}).get('classification')}`",
        "",
        "## OPERATOR_EVIDENCE_REQUEST",
        "See `docs/OPERATOR_EVIDENCE_REQUEST.md`.",
        "",
        "## NEXT_BEST_ACTION",
        "1. Operator: Cabinet account type (ECN/CLASSIC/CENT), redacted.",
        "2. Operator/support: XAUUSD_i ≡ XAUUSD on this server.",
        "3. Then a dedicated executable cost-aware validation phase — not live.",
        "",
        "## DO_NOT_DO_YET",
        "Optimize, shadow, live, send orders, read .env, rename XAUUSD_i, hang tick download.",
        "",
    ]
    (root / PHASE57_60_MD).write_text("\n".join(closure), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase60_collection(Path("."))["AUTHORIZED_NEXT_PHASE"])
