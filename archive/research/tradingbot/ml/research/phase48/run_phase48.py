#!/usr/bin/env python3
"""Phase 48 — Final integration gate after structure + ML signal research."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(name: str) -> dict:
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def run_phase48() -> dict:
    r45 = _load("phase45_final_report.json")
    r46 = _load("phase46_final_report.json")
    r47 = _load("phase47_final_report.json")
    r44 = _load("phase44_final_report.json")

    mean_pf = float(r47.get("mean_best_pf", r44.get("summary", {}).get("mean_best_pf", 0)) or 0)
    mean_auc = float(r47.get("mean_auc", 0) or 0)
    best_ds = r47.get("best_dataset", "v4_full")

    blockers: list[str] = []
    if mean_pf < 1.3:
        blockers.append("PF_BELOW_1.3")
    if mean_auc < 0.55:
        blockers.append("AUC_BELOW_0.55")
    if r46.get("dataset_v6_rows", 0) < 200:
        blockers.append("ML_SIGNAL_POPULATION_TOO_SMALL")

    if not blockers:
        gate = "INTEGRATION_REVIEW_ELIGIBLE"
        verdict = "READY_FOR_INTEGRATION_REVIEW_ONLY"
    elif mean_pf >= 1.0:
        gate = "MARGINAL_CONTINUE_RESEARCH"
        verdict = "CONTINUE_ML_RETRAIN_NOT_FILTER_TUNING"
    else:
        gate = "BLOCK_PRODUCTION_INTEGRATION"
        verdict = "CONTINUE_ML_RETRAIN_NOT_FILTER_TUNING"

    return {
        "now": NOW,
        "verdict": verdict,
        "integration_gate": gate,
        "blockers": blockers,
        "best_dataset": best_ds,
        "metrics": {
            "mean_best_pf": mean_pf,
            "mean_auc": mean_auc,
            "v5_rows": r45.get("dataset_v5_rows"),
            "v6_rows": r46.get("dataset_v6_rows"),
            "v5_verdict": r45.get("verdict"),
            "v6_verdict": r46.get("verdict"),
            "v47_verdict": r47.get("verdict"),
        },
        "recommendation": (
            "Production integration still blocked. Prioritize expanding ML signal capture "
            "across full 2021-2026 overlap and redefining labels on structure events only."
            if blockers
            else "Proceed to read-only integration review with checksum preservation."
        ),
    }


def main() -> None:
    data = run_phase48()
    (ROOT / "phase48_final_report.json").write_text(
        json.dumps({"phase": "48", "title": "Final Integration Gate", **data}, indent=2),
        encoding="utf-8",
    )
    status = {
        "updated_utc": NOW,
        "status": "PHASE_48_COMPLETE",
        "engineering_verdict": data["verdict"],
        "integration_gate": data["integration_gate"],
        "completed_phases": [
            "34A-34D", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44",
            "45", "46", "47", "48",
        ],
        "summary": data["metrics"],
        "blockers": data["blockers"],
        "best_dataset": data["best_dataset"],
        "next_step": data["recommendation"],
    }
    (ROOT / "ENGINEERING_STATUS.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  wrote phase48_final_report.json", flush=True)
    print("  wrote ENGINEERING_STATUS.json", flush=True)
    print(json.dumps({"gate": data["integration_gate"], "best": data["best_dataset"]}, indent=2))


if __name__ == "__main__":
    main()
