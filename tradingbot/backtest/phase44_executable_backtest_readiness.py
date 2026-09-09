"""Phase 44 — executable-backtest cost contract and fail-closed gate.

RESEARCH ONLY. Consumes frozen Phase 40–43 artifacts. Does not rescan,
trade, read .env, import live.py, modify strategy/RiskGate, or invent a
VERIFIED commission schedule. SimulatedBroker is not invoked unless the
gate would pass — and the current evidence does not pass.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json

PHASE = "44"
PHASE44_JSON = "logs/phase44_executable_backtest_readiness.json"
PHASE44_MD = "docs_v2/02_research/PHASE44_EXECUTABLE_BACKTEST_READINESS.md"
PHASE40_JSON = "logs/phase40_full_horizon_validation.json"
PHASE43_JSON = "logs/phase43_broker_cost_execution_validation.json"
UNKNOWN = "UNKNOWN"
NOT_PROVEN = "NOT_PROVEN"
BLOCKED = "BLOCKED"
VERIFIED_TOKENS = frozenset({"VERIFIED", "VERIFIED_SCHEDULE", "VERIFIED_EQUIVALENT"})
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "cost_inputs",
    "readiness",
    "executable",
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


def cost_input(
    *,
    name: str,
    value: Any,
    source: str,
    evidence_status: str,
    unit: str,
    currency: str,
    applicability: str,
    effective_date: str,
    grade: str,
    note: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "source": source,
        "evidence_status": evidence_status,
        "unit": unit,
        "currency": currency,
        "applicability": applicability,
        "effective_date": effective_date,
        "grade": grade,
        "note": note,
    }


def is_verified_status(status: Any) -> bool:
    return str(status or "").upper() in VERIFIED_TOKENS


def build_cost_inputs(p40: dict[str, Any], p43: dict[str, Any]) -> dict[str, Any]:
    comm = p43.get("commission") or {}
    swap = p43.get("swap") or {}
    spread = p43.get("spread") or {}
    slip = p43.get("slippage") or {}
    exe = p43.get("execution") or {}
    return {
        "commission": cost_input(
            name="commission",
            value=None,
            source="Phase 43 / official LiteFinance pages (supporting only)",
            evidence_status=comm.get("status") or UNKNOWN,
            unit="USD_per_lot_or_unknown",
            currency="USD",
            applicability="NOT_PROVEN",
            effective_date=UNKNOWN,
            grade="OBSERVED_ZERO_NOT_PROVEN" if comm.get("classification") else UNKNOWN,
            note="Zeros and generic ECN $5/lot are not a VERIFIED_SCHEDULE.",
        ),
        "spread": cost_input(
            name="spread",
            value={"sidecar_median_price": 0.41, "eval_tape": "OHLC_PROXY"},
            source="Phase 35/38 sidecars; Phase 40 eval tape OHLC",
            evidence_status="PARTIAL",
            unit="price_units",
            currency="USD",
            applicability="sidecar ~15d OBSERVED; 1291d tape PROXY",
            effective_date="sidecar 2026-08-13→2026-08-28",
            grade="PARTIAL",
        ),
        "swap": cost_input(
            name="swap",
            value={"long": swap.get("current_swap_long"), "short": swap.get("current_swap_short")},
            source="MT5 symbol_info XAUUSD_i (Phase 42/43)",
            evidence_status="PARTIAL",
            unit="account_currency_per_lot_per_night",
            currency="USD",
            applicability="CURRENT rate OBSERVED; historical series UNKNOWN",
            effective_date=UNKNOWN,
            grade="BROKER_RATE_ONLY",
        ),
        "slippage": cost_input(
            name="slippage",
            value={"pips": 0.8, "pairs": (slip.get("pairs") if slip else 0)},
            source="BacktestConfig default; request/fill pairs=0",
            evidence_status="MODELED",
            unit="pips",
            currency="n/a",
            applicability="model default; not account-verified",
            effective_date=UNKNOWN,
            grade="MODELED",
        ),
        "fill_logic": cost_input(
            name="fill_logic",
            value="NOT_IDENTIFIABLE",
            source="MT5 history + journal (Phase 39/42/43)",
            evidence_status=UNKNOWN,
            unit="request_fill_pairs",
            currency="n/a",
            applicability="XAUUSD_i pairs=0; price_open is not requested",
            effective_date=UNKNOWN,
            grade="UNKNOWN",
        ),
        "volume": cost_input(
            name="volume",
            value={"min": 0.01, "step": 0.01, "max": 100.0},
            source="MT5 symbol_info XAUUSD_i",
            evidence_status="OBSERVED",
            unit="lots",
            currency="n/a",
            applicability="current REAL XAUUSD_i",
            effective_date=UNKNOWN,
            grade="OBSERVED",
        ),
        "contract_size": cost_input(
            name="contract_size",
            value=100.0,
            source="MT5 symbol_info XAUUSD_i",
            evidence_status="OBSERVED",
            unit="oz_per_lot",
            currency="n/a",
            applicability="current REAL XAUUSD_i; not proven for XAUUSD",
            effective_date=UNKNOWN,
            grade="OBSERVED",
        ),
        "tick_value": cost_input(
            name="tick_value",
            value=1.0,
            source="MT5 symbol_info XAUUSD_i",
            evidence_status="OBSERVED",
            unit="USD_per_tick_per_lot",
            currency="USD",
            applicability="current REAL XAUUSD_i",
            effective_date=UNKNOWN,
            grade="OBSERVED",
        ),
        "tick_size": cost_input(
            name="tick_size",
            value=0.01,
            source="MT5 symbol_info XAUUSD_i",
            evidence_status="OBSERVED",
            unit="price",
            currency="USD",
            applicability="current REAL XAUUSD_i",
            effective_date=UNKNOWN,
            grade="OBSERVED",
        ),
        "execution_assumptions": cost_input(
            name="execution_assumptions",
            value={"trade_exemode": 2, "filling": 1, "deals": (exe.get("deals") if exe else None)},
            source="MT5 symbol_info + history",
            evidence_status="PARTIAL",
            unit="broker_enums",
            currency="n/a",
            applicability="current REAL terminal",
            effective_date=UNKNOWN,
            grade="PARTIAL",
        ),
        "symbol_mapping": cost_input(
            name="symbol_mapping",
            value=(p43.get("symbol") or {}).get("SYMBOL_MAPPING") or NOT_PROVEN,
            source="EV-EQ-01 evaluate_ev_eq_01",
            evidence_status=NOT_PROVEN,
            unit="equivalence",
            currency="n/a",
            applicability="XAUUSD not observed on this REAL terminal",
            effective_date=UNKNOWN,
            grade=NOT_PROVEN,
        ),
        "phase40_raw_expectancy_R": (p40.get("raw_performance") or {}).get("expectancy_R"),
    }


def evaluate_executable_readiness(inputs: dict[str, Any]) -> dict[str, Any]:
    comm = inputs.get("commission") or {}
    mapping = inputs.get("symbol_mapping") or {}
    blockers: list[str] = []
    if not is_verified_status(comm.get("evidence_status")):
        blockers.append("commission evidence_status is not VERIFIED / VERIFIED_SCHEDULE")
    if not is_verified_status(mapping.get("evidence_status")):
        blockers.append("symbol equivalence is NOT_PROVEN — XAUUSD claims remain BLOCKED")
    if str((inputs.get("spread") or {}).get("evidence_status")) in {UNKNOWN, "MODELED"}:
        blockers.append("spread not VERIFIED on evaluation tape")
    if str((inputs.get("fill_logic") or {}).get("evidence_status")) == UNKNOWN:
        blockers.append("request/fill telemetry UNKNOWN — fills must not be fabricated")
    ready = not any("commission" in b for b in blockers) and is_verified_status(comm.get("evidence_status"))
    # Fail-closed: commission UNKNOWN always blocks, even if other items were complete.
    if not is_verified_status(comm.get("evidence_status")):
        ready = False
    return {
        "EXECUTABLE_READY": False if not is_verified_status(comm.get("evidence_status")) else bool(ready),
        "mandatory_commission_verified": is_verified_status(comm.get("evidence_status")),
        "symbol_equivalence_verified": is_verified_status(mapping.get("evidence_status")),
        "blockers": blockers,
        "single_highest_blocker": "commission UNKNOWN / no VERIFIED_SCHEDULE",
        "modeled_not_treated_as_verified": True,
        "observed_zero_not_treated_as_verified_zero": True,
        "existing_engine": (
            "tradingbot/backtest/broker.py::SimulatedBroker already refuses "
            "entry when commission availability is not ZERO or MODELED. "
            "This layer does not weaken that gate and does not call the broker "
            "when commission is UNKNOWN."
        ),
    }


def run_frozen_executable_if_ready(inputs: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed runner. Never fabricates fills or applies invented commission."""
    gate = evaluate_executable_readiness(inputs)
    if not gate["EXECUTABLE_READY"]:
        return {
            "status": BLOCKED,
            "ran": False,
            "reason": gate["single_highest_blocker"],
            "blockers": gate["blockers"],
            "NET_EXPECTANCY": None,
            "NET_PF": None,
            "NET_DD": None,
            "cost_attribution": None,
            "fills_fabricated": False,
            "simulated_broker_invoked": False,
            "strategy_modified": False,
        }
    raise RuntimeError("Verified executable path is not implemented because current evidence is not VERIFIED")


def run_phase44_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p43 = _safe_load_json(root / PHASE43_JSON) or {}
    inputs = build_cost_inputs(p40, p43)
    readiness = evaluate_executable_readiness(inputs)
    executable = run_frozen_executable_if_ready(inputs)
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "phase40_scan_rerun": False,
        "phase_47_started": False,
        "env_accessed": False,
        "cost_inputs": inputs,
        "readiness": readiness,
        "executable": executable,
        "EXECUTABLE_READY": readiness["EXECUTABLE_READY"],
        "EXECUTABLE_RESULT": executable["status"],
        "NET_EXPECTANCY": None,
        "NET_PF": None,
        "NET_DD": None,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "verdict": {
            "overall": "INSUFFICIENT_EVIDENCE",
            "profitability_verdict": "NOT_ISSUED",
            "ready_for_live": False,
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
        "artifacts": {"json": PHASE44_JSON, "md": PHASE44_MD},
    }
    (root / PHASE44_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE44_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = [
        "# Phase 44 — Executable Backtest Readiness",
        "",
        f"**STATUS:** `{payload['status']}`",
        f"**EXECUTABLE_READY:** `{readiness['EXECUTABLE_READY']}`",
        f"**EXECUTABLE_RESULT:** `{executable['status']}`",
        f"**FINAL_GATE:** `{BLOCKED}`",
        "",
        "STOP. This phase does not start Phase 45 by itself; the combined workflow continues only as research.",
        "",
        "## Fail-closed rule",
        "",
        "If commission is not VERIFIED, executable evaluation remains BLOCKED.",
        "Observed zeros and generic ECN $5/lot are not converted into a schedule.",
        "SimulatedBroker was **not** invoked.",
        "",
        f"**Single highest blocker:** `{readiness['single_highest_blocker']}`",
        "",
        "## Cost inputs",
        "",
        "| Input | Status | Source | Applicability |",
        "|---|---|---|---|",
    ]
    for key, row in inputs.items():
        if not isinstance(row, dict) or "evidence_status" not in row:
            continue
        md.append(f"| {row.get('name')} | {row.get('evidence_status')} | {row.get('source')} | {row.get('applicability')} |")
    md += [
        "",
        "## Result",
        "",
        "NET_EXPECTANCY / NET_PF / NET_DD were **not** computed.",
        "No fake executable artifact was created.",
        "",
    ]
    (root / PHASE44_MD).write_text("\n".join(md), encoding="utf-8")
    return payload


if __name__ == "__main__":
    out = run_phase44_collection(Path("."))
    print("READY", out.get("EXECUTABLE_READY"), "RESULT", out.get("EXECUTABLE_RESULT"))
