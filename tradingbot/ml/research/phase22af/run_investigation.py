#!/usr/bin/env python3
"""Phase 22AF — freeze pipeline repair design (research only)."""

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
    from tradingbot.ml.research.phase22af.repair_design import run_design

    now = datetime.now(timezone.utc).isoformat()
    print("Running Phase 22AF freeze pipeline repair design...", flush=True)
    result = run_design()

    mapping = (
        ("freeze_repair_design", "freeze_repair_design.json"),
        ("authority_redesign", "authority_redesign.json"),
        ("required_changes", "required_changes.json"),
        ("safety_guard_design", "safety_guard_design.json"),
        ("migration_plan", "migration_plan.json"),
    )
    for key, fname in mapping:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    contract = {**result["freeze_contract"], "generated_utc": now, "production_modified": False}
    _write("freeze_contract.json", contract)

    final = {
        "phase": "22AF",
        "title": "Freeze Pipeline Repair Design",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "summary": (
            "Minimal safe repair: Optimizer winner → acceptance PASS → contract-driven freeze → "
            "read-only registry → runtime. Remove hardcoded DEFAULT_CONFIG freeze and unguarded "
            "shadow auto-freeze paths. Prerequisite: acceptance rule calibration so gate can open."
        ),
        "authority_chain": result["authority_redesign"]["authority_diagram_ascii"],
        "minimum_production_files": result["required_changes"]["minimum_production_surface"],
        "guard_count": len(result["safety_guard_design"]["reject_conditions"]),
        "migration_phases": [p["name"] for p in result["migration_plan"]["migration_phases"]],
        "prerequisites": result["required_changes"]["prerequisite_work"],
        "blocked_until": result["migration_plan"]["blocked_until"],
    }
    _write("phase22af_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
