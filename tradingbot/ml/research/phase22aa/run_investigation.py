#!/usr/bin/env python3
"""Phase 22AA — overfitting_risk_decreased impact radius forensics."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def main() -> int:
    from tradingbot.ml.research.phase22aa.impact_forensics import run_impact_forensics

    now = datetime.now(timezone.utc).isoformat()
    print("Running Phase 22AA impact radius forensics...", flush=True)
    result = run_impact_forensics()

    mapping = {
        "call_chain.json": result["call_chain"],
        "dependency_graph.json": result["dependency_graph"],
        "threshold_map.json": result["threshold_map"],
        "impact_radius.json": result["impact_radius"],
        "architecture_boundary.json": result["architecture_boundary"],
        "duplicate_logic.json": result["duplicate_logic"],
    }
    for name, payload in mapping.items():
        payload["generated_utc"] = now
        payload["production_modified"] = False
        _write(name, payload)

    final = {
        "phase": "22AA",
        "title": "Impact Radius Forensics — overfitting_risk_decreased",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "anchor_rule": "overfitting_risk_decreased",
        "critical_dependencies": result["impact_radius"]["summary"]["CRITICAL"],
        "safe_dependencies": result["impact_radius"]["summary"]["SAFE"],
        "freeze_in_acceptance_chain": False,
        "health_gate_in_acceptance_chain": False,
        "boundary": result["architecture_boundary"]["boundary_statement"],
        "duplicate_risk_order_locations": 2,
    }
    _write("phase22aa_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
