#!/usr/bin/env python3
"""Phase 22Z — overfitting_risk_decreased rule validation."""

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
        phase9_8_robustness_report_path,
        phase9_8_window_results_path,
        phase9_9_model_comparison_path,
    )
    from tradingbot.ml.research.phase22z.overfitting_rule_validation import run_validation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    comparison = json.loads(phase9_9_model_comparison_path(base_dir).read_text(encoding="utf-8"))
    phase98_robustness = json.loads(phase9_8_robustness_report_path(base_dir).read_text(encoding="utf-8"))
    phase98_windows = json.loads(phase9_8_window_results_path(base_dir).read_text(encoding="utf-8"))

    print("Running Phase 22Z overfitting rule validation...", flush=True)
    result = run_validation(
        comparison,
        phase98_robustness=phase98_robustness,
        phase98_windows=phase98_windows,
    )

    for key in (
        "candidate_overfitting_metrics",
        "baseline_comparison",
        "overfitting_numeric_analysis",
        "rule_correctness_report",
        "candidate_rejection_reason",
    ):
        payload = {**result[key], "generated_utc": now, "production_modified": False}
        _write(f"{key}.json", payload)

    final = {
        "phase": "22Z",
        "title": "Acceptance Rule Validation — overfitting_risk_decreased",
        "generated_utc": now,
        "production_modified": False,
        "verdict": result["verdict"],
        "summary": result["baseline_comparison"]["finding"],
        "rule_statistics": result["rule_correctness_report"]["statistics"],
        "gate_passed_fail_ordinal_count": result["rule_correctness_report"]["statistics"][
            "probability_gate_passed_fail_overfitting_ordinal"
        ],
    }
    _write("phase22z_final_report.json", final)

    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
