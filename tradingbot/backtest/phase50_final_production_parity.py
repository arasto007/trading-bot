"""Phase 50 — final production / live-parity audit.

Static CODE audit. Does not import live.py, read .env, start bot, or trade.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "50"
PHASE50_JSON = "logs/phase50_final_production_parity.json"
PHASE50_MD = "docs_v2/02_research/PHASE50_FINAL_PRODUCTION_PARITY.md"
PHASE50_BLOCKERS_MD = "docs_v2/02_research/PHASE47_50_BLOCKER_MATRIX.md"
PHASE46_JSON = "logs/phase46_production_live_parity_audit.json"
PHASE47_JSON = "logs/phase47_blocker_closure.json"
PHASE48_JSON = "logs/phase48_executable_backtest.json"
PHASE49_JSON = "logs/phase49_final_event_oos_validation.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "parity",
    "contradictions",
    "production_readiness",
    "final_gate",
    "verdict",
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


def run_phase50_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p46 = _safe_load_json(root / PHASE46_JSON) or {}
    p47 = _safe_load_json(root / PHASE47_JSON) or {}
    p48 = _safe_load_json(root / PHASE48_JSON) or {}
    p49 = _safe_load_json(root / PHASE49_JSON) or {}
    parity46 = p46.get("parity") or {}
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "parity": {
            "DATA_PARITY": (parity46.get("DATA_PARITY") or {}).get("status") or "PARTIAL",
            "SIGNAL_PARITY": (parity46.get("SIGNAL_PARITY") or {}).get("status") or "PARTIAL",
            "RISK_PARITY": (parity46.get("RISK_PARITY") or {}).get("status") or "PARTIAL",
            "EXECUTION_PARITY": (parity46.get("EXECUTION_PARITY") or {}).get("status") or "FAIL",
            "BROKER_PARITY": (parity46.get("BROKER_PARITY") or {}).get("status") or "FAIL",
            "CONFIG_PARITY": (parity46.get("CONFIG_PARITY") or {}).get("status") or "PARTIAL",
            "OBSERVABILITY": (parity46.get("OBSERVABILITY") or {}).get("status") or "PARTIAL",
        },
        "contradictions": p46.get("contradictions") or [],
        "production_readiness": "NOT_READY",
        "PRODUCTION_READINESS": "NOT_READY",
        "nogo_for_optimization_or_live": True,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "verdict": {
            "overall": "INSUFFICIENT_EVIDENCE",
            "ready_for_live": False,
            "profitability_verdict": "NOT_ISSUED",
            "robustness": p49.get("robustness_verdict"),
            "executable": p48.get("EXECUTABLE_RESULT"),
            "commission_verified": bool((p47.get("commission") or {}).get("VERIFIED_SCHEDULE")),
        },
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "ORDERS": 0,
            "BOT": "NOT_STARTED",
            "DAEMON": "NOT_STARTED",
            "ML": "NOT_ACTIVATED",
            "RISK_GATE": "NOT_MODIFIED",
            "STRATEGY": "NOT_MODIFIED",
            "EXECUTION_ROUTER": "NOT_MODIFIED",
            "ENV": "NOT_READ",
            "PHASE40_RESCAN": "NO",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE50_JSON, "md": PHASE50_MD, "blockers_md": PHASE50_BLOCKERS_MD},
    }
    (root / PHASE50_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE50_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 50 — Final Production / Live-Parity Audit",
        "",
        f"**PRODUCTION_READINESS:** `NOT_READY`",
        f"**FINAL_GATE:** `{BLOCKED}`",
        f"**NO-GO FOR OPTIMIZATION / LIVE:** `True`",
        "",
        f"- DATA: `{payload['parity']['DATA_PARITY']}`",
        f"- SIGNAL: `{payload['parity']['SIGNAL_PARITY']}`",
        f"- RISK: `{payload['parity']['RISK_PARITY']}`",
        f"- EXECUTION: `{payload['parity']['EXECUTION_PARITY']}`",
        f"- BROKER: `{payload['parity']['BROKER_PARITY']}`",
        f"- CONFIG: `{payload['parity']['CONFIG_PARITY']}`",
        f"- OBSERVABILITY: `{payload['parity']['OBSERVABILITY']}`",
        "",
        "CX-REAL-SYMBOL, UNK-COMMISSION, UNK-REAL-SYMBOL-ENV remain unresolved. `.env` was not read.",
        "STOP AFTER PHASE 50. DO NOT OPTIMIZE. DO NOT TRADE. DO NOT START SHADOW TRADING.",
        "",
    ]
    (root / PHASE50_MD).write_text("\n".join(md), encoding="utf-8")
    blockers = [
        "# Phase 47–50 — Blocker Matrix",
        "",
        "**FINAL_GATE:** `BLOCKED`  **PRODUCTION_READINESS:** `NOT_READY`",
        "",
        "| Blocker | Status | Closed in 47–50? |",
        "|---|---|---|",
        "| Commission VERIFIED_SCHEDULE | UNKNOWN | NO |",
        "| Request/fill pairs | 0 | NO |",
        "| Historical Bid/Ask | PARTIAL | NO |",
        "| Historical swap | UNKNOWN | NO |",
        "| EV-EQ-01 / XAUUSD mapping | NOT_PROVEN | NO |",
        "| Executable evaluation | BLOCKED | NO |",
        "| Cost-aware robustness | MODELED | NO |",
        "| RAW time stability | FRAGILE | NO (finding, not a missing file) |",
        "| Production readiness | NOT_READY | NO |",
        "| REAL symbol .env | UNKNOWN (not read) | NO |",
        "",
        "Correct outcome: **NO-GO FOR OPTIMIZATION / LIVE** until account-applicable commission is VERIFIED and cost-aware event/OOS is no longer FRAGILE.",
        "",
    ]
    (root / PHASE50_BLOCKERS_MD).write_text("\n".join(blockers), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 47–50 (`docs_v2/02_research/PHASE47_BLOCKER_CLOSURE.md`, "
        "`PHASE48_EXECUTABLE_BACKTEST.md`, `PHASE49_FINAL_EVENT_OOS_VALIDATION.md`, "
        "`PHASE50_FINAL_PRODUCTION_PARITY.md`) are research-only final blocker/executable/"
        "robustness/parity layers. They do not authorize live trading, overwrite the frozen "
        "M5 snapshot, optimize, or start shadow trading."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 44–46"
        idx = text.find(marker)
        if idx == -1:
            marker = "Phase 43 (`docs_v2/02_research/PHASE43_BROKER_COST_EXECUTION_VALIDATION.md`)"
            idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 47 blocker closure | `run_phase47_collection()` | n/a | RESEARCH; no .env/MT5/bot | **PASS**; no blocker closed |\n"
        "| Phase 48 executable backtest | `run_phase48_collection()` | n/a | RESEARCH; fail-closed | **PASS**; BLOCKED |\n"
        "| Phase 49 event/OOS validation | `run_phase49_collection()` | n/a | RESEARCH; frozen tape | **PASS**; FRAGILE |\n"
        "| Phase 50 final parity | `run_phase50_collection()` | n/a | RESEARCH/AUDIT; no .env | **PASS**; NOT_READY |"
    )
    if "Phase 47 blocker closure" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase47_blocker_closure.py` — **RESEARCH_ONLY** blocker closure; no .env.\n"
        "`tradingbot/backtest/phase48_executable_backtest.py` — **RESEARCH_ONLY** fail-closed executable gate.\n"
        "`tradingbot/backtest/phase49_final_event_oos_validation.py` — **RESEARCH_ONLY** frozen robustness.\n"
        "`tradingbot/backtest/phase50_final_production_parity.py` — **RESEARCH_ONLY** final live-parity; does not import live.py.\n"
    )
    needle = "`tradingbot/backtest/phase46_production_live_parity_audit.py`"
    if "phase47_blocker_closure.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 47 started | **NO** |", "| Phase 47 started | **YES** |")
    block = f"""

## Final blocker / executable / robustness / parity (Phases 47–50)

| Claim | Status |
|---|---|
| Commission VERIFIED_SCHEDULE | **False** |
| Executable | **BLOCKED** |
| Robustness | **FRAGILE** |
| Production readiness | **NOT_READY** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| NO-GO optimization/live | **YES** |
| Phase 51 started | **NO** |
"""
    if "## Final blocker / executable / robustness / parity (Phases 47–50)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


if __name__ == "__main__":
    print(run_phase50_collection(Path("."))["production_readiness"])
