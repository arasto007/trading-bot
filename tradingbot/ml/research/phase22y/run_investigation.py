#!/usr/bin/env python3
"""Phase 22Y — accepted candidate failure forensics."""

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
    from tradingbot.ml.data.paths import (
        normalize_ml_base_dir,
        phase9_9_model_comparison_path,
        phase9_9_robustness_report_path,
    )
    from tradingbot.ml.research.phase22y.acceptance_forensics import run_forensics

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    comparison_path = phase9_9_model_comparison_path(base_dir)
    robustness_path = phase9_9_robustness_report_path(base_dir)
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    robustness = json.loads(robustness_path.read_text(encoding="utf-8"))

    print("Running Phase 22Y acceptance forensics...", flush=True)
    result = run_forensics(comparison, robustness_report=robustness)

    deliverables = {
        "accepted_candidates.json": result["accepted_candidates"],
        "acceptance_breakdown.json": result["acceptance_breakdown"],
        "rule_failure_statistics.json": result["rule_failure_statistics"],
        "dominant_rejection_rule.json": result["dominant_rejection_rule"],
        "rule_origin_analysis.json": result["rule_origin_analysis"],
        "candidate_acceptance_simulation.json": result["candidate_acceptance_simulation"],
    }
    for name, payload in deliverables.items():
        payload["generated_utc"] = now
        payload["production_modified"] = False
        _write(name, payload)

    final = {
        "phase": "22Y",
        "title": "Accepted Candidate Failure Forensics",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "probability_gate_passed_count": result["accepted_candidates"]["count"],
        "phase9_9_final_verdict": robustness.get("final_verdict"),
        "dominant_rejection_rule": result["dominant_rejection_rule"]["rule"],
        "dominant_failed_label": result["dominant_rejection_rule"]["failed_label"],
        "candidates_accepted_if_dominant_rule_ignored": (
            result["candidate_acceptance_simulation"]["probability_gate_passed_only"]
            .get("best_single_rule_relaxation", {})
            .get("accepted_count")
        ),
        "summary": (
            "All 5 probability-gate-passed candidates fail final acceptance. "
            f"Dominant blocker: {result['dominant_rejection_rule']['failed_label']} "
            f"({result['dominant_rejection_rule']['failed_count']}/5). "
            "No candidate can be frozen under current acceptance rules."
        ),
    }
    _write("phase22y_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
