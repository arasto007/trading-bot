#!/usr/bin/env python3
"""Phase 23A — read-only ML pipeline trace and root cause report."""

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
    from tradingbot.ml.research.phase23a.pipeline_trace import run_investigation

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    result = run_investigation(base_dir=base_dir)

    for key, fname in (
        ("runtime_call_graph", "runtime_call_graph.json"),
        ("feature_flow", "feature_flow.json"),
        ("feature_validation", "feature_validation.json"),
        ("predict_proba_trace", "predict_proba_trace.json"),
        ("signal_pipeline", "signal_pipeline.json"),
        ("hold_chain", "hold_chain.json"),
        ("filter_inventory", "filter_inventory.json"),
        ("counter_trace", "counter_trace.json"),
        ("runtime_vs_research", "runtime_vs_research.json"),
        ("early_exit_analysis", "early_exit_analysis.json"),
        ("root_cause_report", "root_cause_report.json"),
        ("impact_radius", "impact_radius.json"),
        ("repair_plan", "repair_plan.json"),
    ):
        _write(fname, {**result[key], "generated_utc": now})

    final = {
        "phase": "23A",
        "title": "End-to-End ML Pipeline Trace & Root Cause Investigation",
        "mode": "read_only",
        "generated_utc": now,
        "verdict": result["verdict"],
        "primary_root_cause": result["root_cause_report"].get("primary_root_cause"),
        "first_model_pass_zero_location": result["root_cause_report"].get("first_model_pass_zero_location"),
        "model_pass": result["counter_trace"]["counters"].get("model_pass"),
        "decision_hold_count": result["counter_trace"]["counters"].get("decision_hold"),
        "predict_proba_reached_in_runtime_sample": result["feature_validation"]["checks"].get(
            "predict_proba_reached"
        ),
        "summary": result["root_cause_report"].get("narrative"),
    }
    _write("phase23a_final_report.json", final)
    print(json.dumps({"verdict": result["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
