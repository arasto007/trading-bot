#!/usr/bin/env python3
"""Phase 44 — Integration gate synthesis across phases 42-43."""

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


def run_phase44() -> dict:
    r42 = _load("phase42_final_report.json")
    r43 = _load("phase43_final_report.json")
    r41 = _load("phase41_final_report.json")

    mean_pf = float(r43.get("mean_best_pf", r41.get("mean_best_pf", 0)) or 0)
    mean_auc = float(r43.get("mean_auc", r41.get("mean_auc", 0)) or 0)

    blockers: list[str] = []
    if mean_pf < 1.3:
        blockers.append("PF_BELOW_1.3")
    if mean_auc < 0.55:
        blockers.append("AUC_BELOW_0.55")
    if (r42.get("event_bias_verdict") or "") == "SEVERE_EVENT_BIAS":
        blockers.append("SEVERE_EVENT_SAMPLING_BIAS")

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
        "metrics": {
            "mean_best_pf": mean_pf,
            "mean_auc": mean_auc,
            "best_subset": r43.get("best_subset"),
            "parity_verdict": r42.get("parity_verdict"),
            "event_bias_verdict": r42.get("event_bias_verdict"),
        },
        "phase42_verdict": r42.get("verdict"),
        "phase43_verdict": r43.get("verdict"),
        "recommendation": (
            "Do not integrate or tune filters. Next: new label hypothesis on structure events "
            "or production-aligned signal capture for training population."
            if blockers
            else "Proceed to read-only integration review phase with frozen checksum workflow."
        ),
    }


def main() -> None:
    data = run_phase44()
    (ROOT / "phase44_final_report.json").write_text(
        json.dumps({"phase": "44", "title": "Integration Gate Synthesis", **data}, indent=2),
        encoding="utf-8",
    )
    (ROOT / "integration_gate_report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    status = {
        "updated_utc": NOW,
        "status": "PHASE_44_COMPLETE",
        "engineering_verdict": data["verdict"],
        "integration_gate": data["integration_gate"],
        "completed_phases": ["34A-34D", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44"],
        "summary": data["metrics"],
        "blockers": data["blockers"],
        "next_step": data["recommendation"],
    }
    (ROOT / "ENGINEERING_STATUS.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  wrote phase44_final_report.json", flush=True)
    print("  wrote ENGINEERING_STATUS.json", flush=True)
    print(json.dumps({"gate": data["integration_gate"], "blockers": data["blockers"]}, indent=2))


if __name__ == "__main__":
    main()
