"""Phase 108 — spread-path research.

Runs only on local bid/ask/spread files. Does not infer broker economics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import FROZEN, MIN_BIN, PHASE40_JSON, _git_head, _utc_now
from tradingbot.backtest.phase106_non_ohlc_data_inventory import PHASE106_JSON

PHASE = "108"
PHASE108_JSON = "logs/phase108_spread_path_research.json"
PHASE108_MD = "docs/PHASE108_SPREAD_PATH_RESEARCH.md"
BLOCKED = "BLOCKED"
ALLOWED = ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "DATA_MISSING", "INSUFFICIENT_EVIDENCE")
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "SPREAD_DISCRIMINATOR_STATUS",
    "final_gate",
    "production_safety",
    "artifacts",
)


def run_phase108_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p106 = _safe_load_json(root / PHASE106_JSON) or {}
    rows = [
        r
        for r in (p106.get("inventory") or [])
        if r.get("category") in {"spread", "bid_ask"}
    ]
    sources = []
    n_ov = 0
    for r in rows:
        ov = r.get("overlap_events") or {}
        n_ov = max(n_ov, int(ov.get("n_overlap") or 0))
        sources.append(
            {
                "id": r.get("id"),
                "path": r.get("path"),
                "class": r.get("class"),
                "n_overlap": ov.get("n_overlap"),
                "frac": ov.get("frac"),
                "date_start": r.get("date_start"),
                "date_end": r.get("date_end"),
                "columns": r.get("columns"),
            }
        )
    files_exist = any(r.get("exists") for r in rows)
    if n_ov < MIN_BIN:
        status = "DATA_MISSING"
        reason = (
            "Observed bid/ask/spread sidecars do not cover the Phase40 event tape "
            f"(max event overlap={n_ov} < MIN_BIN={MIN_BIN}). OHLC range-proxy spread in ML stores is not observed bid/ask."
        )
    else:
        status = "INSUFFICIENT_EVIDENCE"
        reason = "Sparse overlap is too small to claim a C/D vs E/F spread discriminator."
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
        "files_exist": files_exist,
        "max_event_overlap": n_ov,
        "sources": sources,
        "analyzed": False,
        "SPREAD_DISCRIMINATOR_STATUS": status,
        "reason": reason,
        "evidence_kind": "DATA_MISSING" if status == "DATA_MISSING" else "NON-OHLC-DATA-EVIDENCE",
        "hypotheses": [
            {
                "id": "H108-01",
                "claim": "Historical spread path distinguishes C/D giveback from E/F continuation.",
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
        "artifacts": {"json": PHASE108_JSON, "md": PHASE108_MD},
    }
    (root / PHASE108_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE108_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    (root / PHASE108_MD).write_text(
        "\n".join(
            [
                "# Phase 108 — Spread Path Research",
                "",
                f"**SPREAD_DISCRIMINATOR_STATUS:** `{status}`",
                reason,
                "No spread exit rule. Broker economics not inferred.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(run_phase108_collection(Path("."))["SPREAD_DISCRIMINATOR_STATUS"])
