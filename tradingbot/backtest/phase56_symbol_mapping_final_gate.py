"""Phase 56 — symbol mapping + information-value gate.

Does not modify trading code, optimize, or rewrite Phase 40–53.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.request_fill_telemetry import JOURNAL_MISSING, REQUIRED_FIELDS, audit_journal_schema

PHASE = "56"
PHASE56_JSON = "logs/phase56_symbol_mapping_final_gate.json"
PHASE56_MD = "docs/PHASE56_SYMBOL_MAPPING_FINAL_GATE.md"
PHASE54_56_MD = "docs/PHASE54_56_EVIDENCE_CLOSURE.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE45_JSON = "logs/phase45_event_oos_regime_robustness.json"
PHASE50_JSON = "logs/phase50_final_production_parity.json"
PHASE53_JSON = "logs/phase53_shadow_readiness.json"
PHASE54_JSON = "logs/phase54_account_broker_evidence.json"
PHASE55_JSON = "logs/phase55_cost_scenario_analysis.json"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "gates",
    "INFORMATION_VALUE_RANKING",
    "NEXT_BEST_ACTIONS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _grade(ok: bool, partial: bool = False, unknown: bool = False) -> str:
    if ok:
        return "PASS"
    if unknown:
        return "UNKNOWN"
    if partial:
        return "PARTIAL"
    return "FAIL"


def run_phase56_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p45 = _safe_load_json(root / PHASE45_JSON) or {}
    p50 = _safe_load_json(root / PHASE50_JSON) or {}
    p53 = _safe_load_json(root / PHASE53_JSON) or {}
    p54 = _safe_load_json(root / PHASE54_JSON) or {}
    p55 = _safe_load_json(root / PHASE55_JSON) or {}
    product = str((p54.get("product") or {}).get("ACCOUNT_PRODUCT_STATUS") or UNKNOWN)
    comm = p54.get("commission") or {}
    identity = p54.get("identity") or {}
    parity = p50.get("parity") or {}
    journal_src = ""
    jp = root / "tradingbot/services/trade_journal.py"
    if jp.is_file():
        journal_src = jp.read_text(encoding="utf-8")
    journal_audit = audit_journal_schema(journal_src)
    telemetry = {
        "status": "SCHEMA_ONLY",
        "PASSIVE_READY": True,
        "HISTORICAL_AVAILABLE": False,
        "LIVE_CAPTURE_NOT_ACTIVE": True,
        "wired_into_live": False,
        "required_fields": list(REQUIRED_FIELDS),
        "journal_missing": list(JOURNAL_MISSING),
        "journal_audit": journal_audit,
        "capture_point": "Mt5ExecutionAdapter._place_market_order request dict + result retcode/deal — not wired",
        "retrospective_impossible": [
            "true requested_price vs deal.price",
            "request_ts vs fill_ts latency",
            "partial fill linkage without order/deal tickets stored at send time",
        ],
    }
    g1 = _grade(product.startswith("VERIFIED"))
    g2 = _grade(bool(comm.get("VERIFIED_SCHEDULE")))
    ident = str(identity.get("IDENTITY_STATUS") or NOT_PROVEN)
    g3 = _grade(ident == "PROVEN", partial=ident == "PARTIAL", unknown=ident == NOT_PROVEN)
    if ident == "NOT_PROVEN":
        g3 = "FAIL"
    g4 = "PARTIAL"
    g5 = "PARTIAL"
    g6 = "FAIL"
    g7 = "FAIL"
    g8 = "FAIL" if parity.get("EXECUTION_PARITY") == "FAIL" or parity.get("BROKER_PARITY") == "FAIL" else "PARTIAL"
    gates = {
        "G1_ACCOUNT_PRODUCT_VERIFIED": {"status": g1, "detail": product},
        "G2_COMMISSION_SCHEDULE_VERIFIED": {"status": g2, "detail": comm.get("OBSERVED_COMMISSION_STATUS")},
        "G3_SYMBOL_IDENTITY": {"status": g3, "detail": ident},
        "G4_HISTORICAL_BID_ASK": {"status": g4, "detail": "sidecars exist; eval tape uncovered"},
        "G5_HISTORICAL_SWAP": {"status": g5, "detail": "CURRENT observed; HISTORICAL_RATE_UNKNOWN; MODELED labeled"},
        "G6_REQUEST_FILL_TELEMETRY": {"status": g6, "detail": telemetry["status"]},
        "G7_EXECUTABLE_COST_AWARE_BACKTEST": {"status": g7, "detail": "commission not VERIFIED"},
        "G8_BROKER_EXECUTION_PARITY": {"status": g8, "detail": f"EXEC={parity.get('EXECUTION_PARITY')} BROKER={parity.get('BROKER_PARITY')}"},
    }
    ranking = [
        {
            "rank": 1,
            "blocker": "account product / applicable commission",
            "p_change_decision": "HIGHEST",
            "cost": "LOW",
            "safety": "HIGH — operator cabinet screenshot or support letter; no .env, no orders",
            "reproducible": True,
            "without_live_trading": True,
        },
        {
            "rank": 2,
            "blocker": "XAUUSD ↔ XAUUSD_i official equivalence or both-symbol observation",
            "p_change_decision": "HIGH",
            "cost": "LOW",
            "safety": "HIGH — broker document or catalog on a terminal that lists both",
            "reproducible": True,
            "without_live_trading": True,
        },
        {
            "rank": 3,
            "blocker": "passive request/fill capture (schema exists)",
            "p_change_decision": "HIGH for slippage",
            "cost": "MEDIUM",
            "safety": "HIGH if not wired to send",
            "reproducible": True,
            "without_live_trading": True,
        },
        {
            "rank": 4,
            "blocker": "historical Bid/Ask covering eval tape",
            "p_change_decision": "MEDIUM",
            "cost": "HIGH / hang risk",
            "safety": "MEDIUM — bounded probes only",
            "reproducible": False,
            "without_live_trading": True,
        },
        {
            "rank": 5,
            "blocker": "historical swap series",
            "p_change_decision": "MEDIUM",
            "cost": "HIGH",
            "safety": "HIGH if read-only history",
            "reproducible": False,
            "without_live_trading": True,
        },
    ]
    actions = [
        {
            "id": 1,
            "action": "Obtain a sanitized operator confirmation of LiteFinance product (ECN vs CLASSIC vs CENT) for this REAL login — cabinet or support PDF. Do not read .env.",
            "closes": "G1+G2",
        },
        {
            "id": 2,
            "action": "Obtain official mapping that XAUUSD_i is the tradable REAL alias of XAUUSD on LiteFinance-MT5-Live, or observe both symbols on this account.",
            "closes": "G3 / EV-EQ-01",
        },
        {
            "id": 3,
            "action": "Keep PassiveRequestFillRecorder unwired. When a non-research observer later logs live attempts, store request/deal tickets. Do not send orders from research.",
            "closes": "G6 samples, not historical reconstruction",
        },
    ]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
        "gates": gates,
        "INFORMATION_VALUE_RANKING": ranking,
        "NEXT_BEST_ACTIONS": actions,
        "telemetry": telemetry,
        "bid_ask": (p54.get("bid_ask") or {}).get("status") or "PARTIAL",
        "swap": (p54.get("swap") or {}),
        "ecn_scenario_net_event_R": (p55.get("scenarios") or {}).get("A_ECN", {}).get("net_event_expectancy_R"),
        "classic_scenario_net": p55.get("CLASSIC_SCENARIO_NET_EXPECTANCY"),
        "robustness": p45.get("robustness_verdict"),
        "shadow": p53.get("SHADOW"),
        "GO_CONDITIONS": [
            "G1 PASS",
            "G2 PASS",
            "G3 PASS",
            "executable net after verified costs",
            "robustness not FRAGILE after costs",
            "G8 no longer FAIL",
        ],
        "NO_GO_CONDITIONS": [
            "commission UNKNOWN or not account-applicable",
            "EV-EQ-01 NOT_PROVEN",
            "robustness FRAGILE",
            "execution/broker parity FAIL",
        ],
        "OPTIMIZATION_ALLOWED": False,
        "LIVE_TRADING_ALLOWED": False,
        "SHADOW_ACTIVATION_ALLOWED": False,
        "project_stopped": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "STRATEGY": "NOT_MODIFIED",
            "RISK_GATE": "NOT_MODIFIED",
            "EXECUTION_ROUTER": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE56_JSON, "md": PHASE56_MD, "closure_md": PHASE54_56_MD},
    }
    (root / PHASE56_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE56_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 56 — Symbol Mapping + Information-Value Gate",
        "",
        f"**FINAL_GATE:** `{BLOCKED}`",
        "**OPTIMIZATION_ALLOWED:** `FALSE`",
        "**LIVE_TRADING_ALLOWED:** `FALSE`",
        "**Project stopped:** `FALSE` — continue reducing uncertainty.",
        "",
        "## Gates",
        "",
    ]
    for key, row in gates.items():
        md.append(f"- `{key}`: **{row['status']}** — {row['detail']}")
    md.extend(
        [
            "",
            "## NEXT_BEST_ACTIONS",
            "",
            "1. Sanitized operator product confirmation (ECN/CLASSIC/CENT) — no .env, no orders.",
            "2. Official XAUUSD ↔ XAUUSD_i equivalence or both-symbol observation.",
            "3. Keep request/fill schema passive; do not send orders to generate samples.",
            "",
        ]
    )
    (root / PHASE56_MD).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE56_MD).write_text("\n".join(md), encoding="utf-8")
    closure = [
        "# Phase 54–56 — Evidence Closure",
        "",
        "## EXECUTIVE_STATUS",
        "",
        "Research advanced. Live/optimization remain NO-GO. Uncertainty was reduced by converting official pages and ECN $5/lot into an explicit SCENARIO, not by declaring a verified schedule.",
        "",
        "## ACCOUNT_STATUS",
        f"`{product}`",
        "",
        "## BROKER_STATUS",
        "LiteFinance Global LLC / LiteFinance-MT5-Live / REAL pattern.",
        "",
        "## COMMISSION_STATUS",
        f"`{comm.get('OBSERVED_COMMISSION_STATUS')}` — VERIFIED_SCHEDULE=`{comm.get('VERIFIED_SCHEDULE')}`",
        "",
        "## SYMBOL_STATUS",
        f"IDENTITY `{ident}`  EV-EQ-01 `{identity.get('EV_EQ_01')}`",
        "",
        "## REQUEST_FILL_STATUS",
        "0 pairs. SCHEMA_ONLY / PASSIVE_READY / LIVE_CAPTURE_NOT_ACTIVE / HISTORICAL_AVAILABLE=FALSE",
        "",
        "## BID_ASK_STATUS",
        "PARTIAL — existing sidecars; eval tape uncovered; bounded probe only.",
        "",
        "## SWAP_STATUS",
        "CURRENT_BROKER_RATE observed or reused. HISTORICAL_RATE_UNKNOWN. Not back-filled from today.",
        "",
        "## EXECUTION_STATUS",
        f"EXECUTION_PARITY `{parity.get('EXECUTION_PARITY')}`  BROKER_PARITY `{parity.get('BROKER_PARITY')}`",
        "",
        "## COST_SCENARIO_STATUS",
        f"ECN net event `{payload.get('ecn_scenario_net_event_R')}` R (SCENARIO). CLASSIC/CENT conversion UNKNOWN.",
        "",
        "## FINAL_GATE",
        "`BLOCKED` for live/optimization. Research continues.",
        "",
        "## BLOCKERS",
        "1. Account-applicable commission UNKNOWN",
        "2. EV-EQ-01 NOT_PROVEN",
        "3. Request/fill pairs = 0",
        "4. Historical Bid/Ask incomplete",
        "5. Historical swap UNKNOWN",
        "6. Execution/broker parity FAIL",
        "",
        "## WHAT_WE_NOW_KNOW",
        "- ECN $5/lot can be expressed as ~commission_R per event using XAUUSD_i tick economics and median SL, as a SCENARIO.",
        "- CLASSIC/CENT '14' cannot be converted without invention.",
        "- RAW edge is smaller than spread/slip cost uncertainty even before verified commission.",
        "- XAUUSD absence on this terminal is NOT_OBSERVED, not CONTRADICTED.",
        "",
        "## WHAT_WE_STILL_DO_NOT_KNOW",
        "- Whether this REAL account is ECN, CLASSIC, or CENT.",
        "- Whether XAUUSD_i is the broker alias of XAUUSD for this account.",
        "- Realized request→fill slippage.",
        "",
        "## NEXT_BEST_ACTIONS",
        "1. Operator product confirmation (cabinet/support), sanitized.",
        "2. Official symbol-equivalence statement or both-symbol catalog evidence.",
        "3. Leave telemetry unwired; do not generate fills.",
        "",
        "## NO_GO CONDITIONS",
        "Commission UNKNOWN; EV-EQ-01 NOT_PROVEN; robustness FRAGILE; parity FAIL.",
        "",
        "## GO CONDITIONS",
        "Verified account-applicable schedule; proven identity; cost-aware executable net; robustness not FRAGILE; parity no longer FAIL.",
        "",
    ]
    (root / PHASE54_56_MD).write_text("\n".join(closure), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 54–56 (`docs/PHASE54_ACCOUNT_BROKER_EVIDENCE.md`, "
        "`docs/PHASE55_COST_SCENARIO_ANALYSIS.md`, `docs/PHASE56_SYMBOL_MAPPING_FINAL_GATE.md`) "
        "are research-only account/broker discovery, cost scenarios, and information-value ranking. "
        "They do not authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 51–53"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 54 account/broker evidence | `run_phase54_collection()` | n/a | RESEARCH; attach-if-running | **PASS**; product not verified |\n"
        "| Phase 55 cost scenarios | `run_phase55_collection()` | n/a | RESEARCH; SCENARIO only | **PASS**; CLASSIC/CENT UNKNOWN |\n"
        "| Phase 56 information-value gate | `run_phase56_collection()` | n/a | RESEARCH; no optimize | **PASS**; FINAL_GATE BLOCKED |"
    )
    if "Phase 54 account/broker evidence" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase54_account_broker_evidence.py` — **RESEARCH_ONLY** attach-if-running account/symbol forensics; no .env.\n"
        "`tradingbot/backtest/phase55_cost_scenario_analysis.py` — **RESEARCH_ONLY** ECN/CLASSIC/CENT scenarios; not account-verified.\n"
        "`tradingbot/backtest/phase56_symbol_mapping_final_gate.py` — **RESEARCH_ONLY** information-value ranking; does not optimize.\n"
    )
    needle = "`tradingbot/backtest/phase53_shadow_readiness.py`"
    if "phase54_account_broker_evidence.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 54 started | **NO** |", "| Phase 54 started | **YES** |")
    block = f"""

## Account/broker discovery / cost scenarios / information-value (Phases 54–56)

| Claim | Status |
|---|---|
| Account product | **{(payload.get("gates") or {}).get("G1_ACCOUNT_PRODUCT_VERIFIED", {}).get("detail") or UNKNOWN}** |
| Commission VERIFIED_SCHEDULE | **False** |
| EV-EQ-01 | **NOT_PROVEN** (absence ≠ CONTRADICTED) |
| CLASSIC/CENT R conversion | **UNKNOWN** |
| ECN $5/lot | **SCENARIO only** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Optimization / live | **NO-GO** |
| Project stopped | **NO** |
| Phase 57 started | **NO** |
"""
    if "## Account/broker discovery / cost scenarios / information-value (Phases 54–56)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


if __name__ == "__main__":
    print(run_phase56_collection(Path("."))["FINAL_GATE"])
