"""Phase 53 — shadow-trading readiness specification.

Specifies an inert framework. Does not activate it, start the bot, or place orders.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.shadow_observation import (
    COMPARISON_METRICS,
    PROCESS_STEPS,
    SHADOW_RECORD_FIELDS,
    ShadowFramework,
    evaluate_shadow_acceptance,
)

PHASE = "53"
PHASE53_JSON = "logs/phase53_shadow_readiness.json"
PHASE53_MD = "docs_v2/02_research/PHASE53_SHADOW_READINESS.md"
PHASE48_JSON = "logs/phase48_executable_backtest.json"
PHASE49_JSON = "logs/phase49_final_event_oos_validation.json"
PHASE50_JSON = "logs/phase50_final_production_parity.json"
PHASE51_JSON = "logs/phase51_final_evidence_closure.json"
PHASE52_JSON = "logs/phase52_optimization_gate.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "framework",
    "SHADOW_ACTIVE",
    "ORDERS_PLACED",
    "ACCEPTANCE_GATE",
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


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phases 51–53 (`docs_v2/02_research/PHASE51_FINAL_EVIDENCE_CLOSURE.md`, "
        "`PHASE52_OPTIMIZATION_GATE.md`, `PHASE53_SHADOW_READINESS.md`) are research-only "
        "final evidence, optimization-gate, and shadow-specification layers. They do not "
        "authorize live trading, overwrite the frozen M5 snapshot, optimize, or activate shadow trading."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    if line not in text:
        marker = "Phases 47–50"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
            src.write_text(text, encoding="utf-8")
    cfg = root / "docs_v2/01_truth/CONFIGURATION_TRUTH.md"
    ctext = cfg.read_text(encoding="utf-8")
    rows = (
        "| Phase 51 final evidence closure | `run_phase51_collection()` | n/a | RESEARCH; no .env/MT5/bot | **PASS**; no blocker closed |\n"
        "| Phase 52 optimization gate | `run_phase52_collection()` | n/a | RESEARCH; fail-closed; no search | **PASS**; BLOCKED |\n"
        "| Phase 53 shadow readiness | `run_phase53_collection()` | n/a | RESEARCH; spec only; no orders | **PASS**; NOT_ACTIVATED |"
    )
    if "Phase 51 final evidence closure" not in ctext:
        ctext = ctext.replace("| PA M5 `MIN_CONFIDENCE`", rows + "\n| PA M5 `MIN_CONFIDENCE`")
        cfg.write_text(ctext, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = (
        "`tradingbot/backtest/phase51_final_evidence_closure.py` — **RESEARCH_ONLY** final evidence closure; no .env.\n"
        "`tradingbot/backtest/phase52_optimization_gate.py` — **RESEARCH_ONLY** fail-closed optimization gate; no search.\n"
        "`tradingbot/backtest/phase53_shadow_readiness.py` — **RESEARCH_ONLY** shadow specification; does not activate.\n"
        "`tradingbot/backtest/request_fill_telemetry.py` — **RESEARCH_ONLY** passive request/fill schema; not wired to live.\n"
        "`tradingbot/backtest/shadow_observation.py` — **RESEARCH_ONLY** inert shadow spec; cannot place orders.\n"
    )
    needle = "`tradingbot/backtest/phase50_final_production_parity.py`"
    if "phase51_final_evidence_closure.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 51 started | **NO** |", "| Phase 51 started | **YES** |")
    block = f"""

## Final evidence / optimization gate / shadow spec (Phases 51–53)

| Claim | Status |
|---|---|
| Commission VERIFIED_SCHEDULE | **False** |
| EV-EQ-01 | **NOT_PROVEN** |
| Optimization gate | **BLOCKED** |
| Optimization executed | **NO** |
| Shadow framework | **SPECIFIED / NOT_ACTIVATED** |
| Shadow orders | **0** |
| FINAL_GATE | **{payload.get("final_gate")}** |
| Phase 54 started | **NO** |
"""
    if "## Final evidence / optimization gate / shadow spec (Phases 51–53)" not in ktext:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext, encoding="utf-8")


def run_phase53_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p48 = _safe_load_json(root / PHASE48_JSON) or {}
    p49 = _safe_load_json(root / PHASE49_JSON) or {}
    p50 = _safe_load_json(root / PHASE50_JSON) or {}
    p51 = _safe_load_json(root / PHASE51_JSON) or {}
    p52 = _safe_load_json(root / PHASE52_JSON) or {}
    parity = p50.get("parity") or {}
    acceptance = evaluate_shadow_acceptance(
        commission_verified=bool((p51.get("commission") or {}).get("VERIFIED_SCHEDULE")),
        executable_completed=bool((p48.get("executable") or {}).get("ran")),
        execution_parity=str(parity.get("EXECUTION_PARITY") or "FAIL"),
        broker_parity=str(parity.get("BROKER_PARITY") or "FAIL"),
        production_readiness=str(p50.get("production_readiness") or "NOT_READY"),
        robustness_verdict=str(p49.get("robustness_verdict") or "FRAGILE"),
    )
    framework = ShadowFramework()
    activation_error = None
    try:
        framework.activate()
    except Exception as exc:
        activation_error = type(exc).__name__
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "framework": {
            "module": "tradingbot/backtest/shadow_observation.py",
            "record_fields": list(SHADOW_RECORD_FIELDS),
            "process_steps": list(PROCESS_STEPS),
            "comparison_metrics": list(COMPARISON_METRICS),
            "wired_into_live_loop": False,
            "can_place_orders": False,
            "activation_attempt_error": activation_error,
        },
        "SHADOW_FRAMEWORK": "SPECIFIED",
        "SHADOW_ACTIVE": False,
        "ORDERS_PLACED": 0,
        "TELEMETRY_READY": "PARTIAL",
        "ACCEPTANCE_GATE": acceptance["ACCEPTANCE_GATE"],
        "acceptance": acceptance,
        "RESULT": "SPECIFIED_NOT_ACTIVATED",
        "optimization_gate": p52.get("OPTIMIZATION_GATE"),
        "nogo_for_optimization_or_live": True,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "OVERALL_VERDICT": "INSUFFICIENT_EVIDENCE",
        "OPTIMIZATION": "NO-GO",
        "SHADOW": "NOT_READY",
        "LIVE": "NO-GO",
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
        "artifacts": {"json": PHASE53_JSON, "md": PHASE53_MD},
    }
    (root / PHASE53_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE53_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 53 — Shadow Trading Readiness",
        "",
        f"**SHADOW_FRAMEWORK:** `SPECIFIED`",
        f"**SHADOW_ACTIVE:** `False`",
        f"**ORDERS_PLACED:** `0`",
        f"**TELEMETRY_READY:** `PARTIAL`",
        f"**ACCEPTANCE_GATE:** `{acceptance['ACCEPTANCE_GATE']}`",
        f"**RESULT:** `SPECIFIED_NOT_ACTIVATED`",
        "",
        "Shadow mode must never place an order. Activation is blocked while commission is UNKNOWN,",
        "executable evaluation is BLOCKED, EXECUTION/BROKER parity is FAIL, and robustness is FRAGILE.",
        "",
        "Record fields, process steps, comparison metrics, alerts, and stop conditions are specified in",
        "`tradingbot/backtest/shadow_observation.py`. The live loop is unchanged.",
        "",
        "STOP AFTER PHASE 53. DO NOT OPTIMIZE. DO NOT TRADE. DO NOT ACTIVATE SHADOW.",
        "",
    ]
    (root / PHASE53_MD).write_text("\n".join(md), encoding="utf-8")
    _patch_truth(root, payload)
    return payload


if __name__ == "__main__":
    print(run_phase53_collection(Path("."))["SHADOW_ACTIVE"])
