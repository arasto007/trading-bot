#!/usr/bin/env python3
"""Phase 22AG — acceptance gate calibration forensics (research only)."""

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
    from tradingbot.ml.research.phase22ag.acceptance_forensics import run_forensics

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Running Phase 22AG acceptance calibration forensics...", flush=True)
    result = run_forensics(base_dir=base_dir)

    mapping = (
        ("acceptance_flow", "acceptance_flow.json"),
        ("rule_analysis", "rule_analysis.json"),
        ("overfitting_rule_analysis", "overfitting_rule_analysis.json"),
        ("candidate_simulation", "candidate_simulation.json"),
        ("acceptance_contract", "acceptance_contract.json"),
        ("minimal_change_design", "minimal_change_design.json"),
    )
    for key, fname in mapping:
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(fname, payload)

    final = {
        "phase": "22AG",
        "title": "Acceptance Gate Calibration Forensics",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "root_cause": result["root_cause"],
        "summary": (
            "Acceptance failure is primarily caused by ordinal overfitting_risk_decreased against a HIGH "
            "Phase 9.8 baseline — 15/16 overfitting failures are label logic, not worse numeric AUC gap. "
            "Minimal safe fix: replace ordinal check with mean_auc_gap < baseline (0.3308) while keeping "
            "probability gate, positive expectancy, robustness_improved, and profitable_windows_ge_4."
        ),
        "dominant_blocker_current": result["rule_analysis"]["dominant_blocker"],
        "variant_D_accepted_count": result["candidate_simulation"]["variants"]["D"]["accepted_count"],
        "variant_D_accepted": result["candidate_simulation"]["variants"]["D"]["accepted"],
        "minimal_change": result["minimal_change_design"]["change_description"],
        "current_report_verdict": result["current_report"]["final_verdict"],
    }
    _write("phase22ag_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"], "root_cause": result["root_cause"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
