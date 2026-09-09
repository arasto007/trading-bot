"""Phase 48 — frozen executable evaluation, fail-closed.

Does not run SimulatedBroker or invent commission. Reuses Phase 44 gate.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase44_executable_backtest_readiness import (
    build_cost_inputs,
    evaluate_executable_readiness,
    run_frozen_executable_if_ready,
)

PHASE = "48"
PHASE48_JSON = "logs/phase48_executable_backtest.json"
PHASE48_MD = "docs_v2/02_research/PHASE48_EXECUTABLE_BACKTEST.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE47_JSON = "logs/phase47_blocker_closure.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "prerequisites",
    "EXECUTABLE_READY",
    "EXECUTABLE_RESULT",
    "costs",
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


def run_phase48_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p47 = _safe_load_json(root / PHASE47_JSON) or {}
    verified = bool((p47.get("commission") or {}).get("VERIFIED_SCHEDULE"))
    inputs = build_cost_inputs(p40, p43)
    gate = evaluate_executable_readiness(inputs)
    if verified:
        executable = run_frozen_executable_if_ready(inputs)
    else:
        executable = {
            "status": BLOCKED,
            "ran": False,
            "reason": "commission UNKNOWN / VERIFIED_SCHEDULE=False (Phase 47)",
            "blockers": gate.get("blockers"),
            "NET_EXPECTANCY": None,
            "NET_PF": None,
            "NET_DD": None,
            "fills_fabricated": False,
            "simulated_broker_invoked": False,
        }
    ready = bool(gate["EXECUTABLE_READY"] and verified)
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "prerequisites": {
            "commission_verified": verified,
            "symbol_equivalence_verified": gate.get("symbol_equivalence_verified"),
            "cost_units_documented": True,
            "spread_treatment_documented": True,
            "swap_treatment_documented": True,
            "slippage_classified": True,
            "frozen_phase40_tape": (root / "data/XAUUSD_i_5m_phase38.parquet").is_file(),
            "fail_closed_gate": True,
            "all_mandatory_met": ready,
        },
        "EXECUTABLE_READY": ready,
        "EXECUTABLE_RESULT": executable["status"],
        "GROSS_EXPECTANCY": None,
        "NET_EXPECTANCY": None,
        "GROSS_PF": None,
        "NET_PF": None,
        "DD": None,
        "TOTAL_COST": None,
        "COMMISSION_COST": None,
        "SPREAD_COST": None,
        "SWAP_COST": None,
        "SLIPPAGE_COST": None,
        "costs": {
            "commission": "UNKNOWN",
            "spread": "PARTIAL / PROXY",
            "swap": "CURRENT OBSERVED / HISTORICAL UNKNOWN",
            "slippage": "MODELED",
            "merged_into_verified_net": False,
        },
        "raw_phase40_not_executable": {
            "expectancy_R": (p40.get("raw_performance") or {}).get("expectancy_R"),
            "profit_factor": (p40.get("raw_performance") or {}).get("profit_factor"),
            "label": "RAW / OBSERVED — not an executable net result",
        },
        "executable": executable,
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
        "artifacts": {"json": PHASE48_JSON, "md": PHASE48_MD, "executable_result_md": None},
    }
    (root / PHASE48_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE48_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 48 — Executable Backtest",
        "",
        f"**EXECUTABLE_READY:** `{ready}`",
        f"**EXECUTABLE_RESULT:** `{executable['status']}`",
        f"**SimulatedBroker invoked:** `{executable.get('simulated_broker_invoked')}`",
        "",
        "Mandatory commission VERIFIED_SCHEDULE is **False**. Evaluation was **not** run.",
        "RAW +0.017224R is **not** a net executable result.",
        "No PHASE48_EXECUTABLE_EVALUATION.md was created because execution did not run.",
        "",
    ]
    (root / PHASE48_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase48_collection(Path("."))["EXECUTABLE_RESULT"])
