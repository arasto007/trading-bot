#!/usr/bin/env python3
"""Phase 22AB — freeze path authority forensics."""

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
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.research.phase22ab.freeze_forensics import run_forensics

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AB freeze authority forensics...", flush=True)
    result = run_forensics(base_dir=base_dir)

    for key, fname in (
        ("freeze_call_graph", "freeze_call_graph.json"),
        ("acceptance_vs_freeze_flow", "acceptance_vs_freeze_flow.json"),
        ("historical_freeze_evidence", "historical_freeze_evidence.json"),
        ("freeze_guard_analysis", "freeze_guard_analysis.json"),
        ("freeze_authority_classification", "freeze_authority_classification.json"),
        ("impact_radius", "impact_radius.json"),
        ("root_cause_report", "root_cause_report.json"),
    ):
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = {
        "phase": "22AB",
        "title": "Freeze Path Authority Forensics",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "freeze_bypasses_acceptance": True,
        "multiple_freeze_paths": True,
        "acceptance_must_pass": False,
        "root_cause_summary": result["root_cause_report"]["answer"],
        "frozen_candidate": result["historical_freeze_evidence"]["frozen_candidate_id"],
        "current_acceptance_verdict": result["historical_freeze_evidence"]["current_acceptance_verdict"],
        "design_vs_defect": result["freeze_authority_classification"]["intentional_vs_defect"]["conclusion"],
    }
    _write("phase22ab_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
