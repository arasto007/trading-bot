"""Phase 52 — conditional optimization gate.

Does not optimize. Evaluates the 13 mandatory conditions against frozen
Phase 40–51 evidence. Fail-closed.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.optimization_gate import evaluate_optimization_gate
from tradingbot.backtest.phase44_executable_backtest_readiness import (
    build_cost_inputs,
    evaluate_executable_readiness,
)

PHASE = "52"
PHASE52_JSON = "logs/phase52_optimization_gate.json"
PHASE52_MD = "docs_v2/02_research/PHASE52_OPTIMIZATION_GATE.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
PHASE48_JSON = "logs/phase48_executable_backtest.json"
PHASE49_JSON = "logs/phase49_final_event_oos_validation.json"
PHASE50_JSON = "logs/phase50_final_production_parity.json"
PHASE51_JSON = "logs/phase51_final_evidence_closure.json"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"
FROZEN_TAPE_FINGERPRINT = "222e75c592115c8e7449d55257373824c1ed3562cff6708f5ea7a3cedb42bfb5"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "gate",
    "OPTIMIZATION_GATE",
    "OPTIMIZATION_EXECUTED",
    "BASELINE_PRESERVED",
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


def run_phase52_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    p48 = _safe_load_json(root / PHASE48_JSON) or {}
    p49 = _safe_load_json(root / PHASE49_JSON) or {}
    p50 = _safe_load_json(root / PHASE50_JSON) or {}
    p51 = _safe_load_json(root / PHASE51_JSON) or {}
    verified = bool((p51.get("commission") or {}).get("VERIFIED_SCHEDULE"))
    symbol_ok = str((p51.get("symbol") or {}).get("EV_EQ_01")) == "VERIFIED"
    executable_ran = bool((p48.get("executable") or {}).get("ran"))
    parity = p50.get("parity") or {}
    production_fail = parity.get("EXECUTION_PARITY") == "FAIL" or parity.get("BROKER_PARITY") == "FAIL"
    robustness = str(p49.get("robustness_verdict") or "FRAGILE")
    recent = float(((p49.get("time_stability") or {}).get("recent_180d_signal_expectancy_R")) or -0.467633)
    bootstrap = p49.get("bootstrap") or {}
    gate = evaluate_optimization_gate(
        commission_verified=verified,
        symbol_equivalence_verified=symbol_ok,
        executable_completed=executable_ran,
        net_expectancy_R=p48.get("NET_EXPECTANCY"),
        event_net_expectancy_R=None,
        oos_net_expectancy_R=None,
        oos_sample_sufficient=True,
        bootstrap_obviously_fragile=bool(bootstrap.get("ci_crosses_zero", True)),
        recent_materially_contradictory=recent < 0,
        production_parity_fail=production_fail,
        material_unresolved_blocker=not verified,
        robustness_verdict=robustness,
        evidence_margin_exceeds_cost_uncertainty=False,
    )
    exe_inputs = build_cost_inputs(p40, p43)
    exe_gate = evaluate_executable_readiness(exe_inputs)
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN_TAPE_FINGERPRINT,
        "gate": gate,
        "executable_gate": {
            "EXECUTABLE_READY": exe_gate.get("EXECUTABLE_READY"),
            "blocked_by_unknown_commission": not bool(exe_gate.get("mandatory_commission_verified")),
        },
        "OPTIMIZATION_GATE": gate["OPTIMIZATION_GATE"],
        "CONDITIONS_PASSED": [row["id"] for row in gate["passed"]],
        "CONDITIONS_FAILED": [row["id"] for row in gate["failed"]],
        "OPTIMIZATION_EXECUTED": False,
        "BASELINE_PRESERVED": True,
        "parameters_searched": False,
        "oos_used_for_selection": False,
        "genetic": False,
        "ml_activated": False,
        "predefined_search_space": {
            "status": "NOT_SEARCHED",
            "reason": "OPTIMIZATION_GATE=BLOCKED",
            "would_use_train_val_only": True,
            "would_forbid_oos_selection": True,
            "would_forbid_genetic_until_gate_passed": True,
        },
        "RESULT": "BLOCKED_NO_SEARCH",
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
        "artifacts": {"json": PHASE52_JSON, "md": PHASE52_MD},
    }
    (root / PHASE52_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE52_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    failed = ", ".join(payload["CONDITIONS_FAILED"])
    md = [
        "# Phase 52 — Conditional Optimization Gate",
        "",
        f"**OPTIMIZATION_GATE:** `{gate['OPTIMIZATION_GATE']}`",
        f"**CONDITIONS_PASSED:** `{gate['conditions_passed']}/{gate['condition_count']}`",
        f"**OPTIMIZATION_EXECUTED:** `False`",
        f"**BASELINE_PRESERVED:** `True`",
        f"**RESULT:** `BLOCKED_NO_SEARCH`",
        "",
        "Optimization is allowed only after a frozen, cost-aware, non-fragile baseline.",
        "RAW/OOS positives are **not** permission to search parameters.",
        "",
        f"Failed conditions: `{failed}`",
        "",
        "No walk-forward search. No genetic search. No OOS selection. No strategy rewrite.",
        "",
    ]
    (root / PHASE52_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(run_phase52_collection(Path("."))["OPTIMIZATION_GATE"])
