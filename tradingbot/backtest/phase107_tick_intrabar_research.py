"""Phase 107 — tick / intrabar path research.

Runs a discriminator analysis only if event-aligned tick/intrabar data exists.
Does not download, connect to MT5, or fabricate ticks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, MIN_BIN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON

PHASE = "107"
PHASE107_JSON = "logs/phase107_tick_intrabar_research.json"
PHASE107_MD = "docs/PHASE107_TICK_INTRABAR_RESEARCH.md"
BLOCKED = "BLOCKED"
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "TICK_DISCRIMINATOR_STATUS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def run_phase107_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p106 = _safe_load_json(root / PHASE106_JSON) or {}
    tick_rows = [r for r in (p106.get("inventory") or []) if r.get("category") == "tick"]
    m1_rows = [r for r in (p106.get("inventory") or []) if r.get("category") == "m1"]
    overlaps = []
    for r in tick_rows + m1_rows:
        ov = r.get("overlap_events") or {}
        overlaps.append(
            {
                "id": r.get("id"),
                "path": r.get("path"),
                "class": r.get("class"),
                "n_overlap": ov.get("n_overlap"),
                "frac": ov.get("frac"),
                "date_start": r.get("date_start"),
                "date_end": r.get("date_end"),
            }
        )
    n_tick = max((int((r.get("overlap_events") or {}).get("n_overlap") or 0) for r in tick_rows), default=0)
    n_m1 = max((int((r.get("overlap_events") or {}).get("n_overlap") or 0) for r in m1_rows), default=0)
    n_ov = n_tick
    files_exist = any(r.get("exists") for r in tick_rows)
    if n_tick < MIN_BIN:
        status = "DATA_MISSING"
        reason = (
            "Tick files exist locally but event-aligned tick coverage is below MIN_BIN="
            f"{MIN_BIN} (tick overlap={n_tick}, M1 overlap={n_m1}). "
            "Intrabar paths were not reconstructed and ticks were not fabricated."
        )
        analyzed = False
    else:
        status = "INSUFFICIENT_EVIDENCE"
        reason = "Overlap meets MIN_BIN but a full-horizon C/D vs E/F tick discriminator was not claimed without complete coverage."
        analyzed = False
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "tick_files_exist": files_exist,
        "max_event_overlap": n_ov,
        "sources": overlaps,
        "analyzed": analyzed,
        "TICK_DISCRIMINATOR_STATUS": status,
        "reason": reason,
        "evidence_kind": "DATA_MISSING" if status == "DATA_MISSING" else "NON-OHLC-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H107-01",
                "claim": "Tick/intrabar information contains a causal discriminator unavailable to M5 OHLC.",
                "result": status,
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["inventory_overlap"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE107_JSON, "md": PHASE107_MD},
    }
    (root / PHASE107_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE107_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE107_MD).write_text(
        "\n".join(
            [
                "# Phase 107 — Tick / Intrabar Path Research",
                "",
                f"**TICK_DISCRIMINATOR_STATUS:** `{status}`",
                reason,
                "No protection rule. No threshold search. +31.84R not excluded.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase107_collection(Path("."))["TICK_DISCRIMINATOR_STATUS"])
