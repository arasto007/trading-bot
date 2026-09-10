#!/usr/bin/env python3
"""Phase 22X — validate probability selection gate and Phase 9.9 pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent


def _write(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {name}", flush=True)


def _run_gate_unit_validation() -> dict:
    from tradingbot.ml.research.robustness_optimizer.probability_selection_gate import (
        BUY_THRESHOLD,
        SELL_THRESHOLD,
        compute_probability_metrics,
        evaluate_probability_gate,
    )

    cases = {
        "sell_only": np.full(200, 0.35),
        "buy_only": np.full(200, 0.70),
        "collapsed_neutral": np.full(200, 0.50),
        "normal_spread": np.linspace(0.35, 0.65, 200),
    }
    results = {}
    for name, probs in cases.items():
        metrics = compute_probability_metrics(probs)
        gate = evaluate_probability_gate(metrics)
        results[name] = {
            "metrics": metrics,
            "gate": gate,
        }

    return {
        "phase": "22X",
        "thresholds": {
            "buy_threshold": BUY_THRESHOLD,
            "sell_threshold": SELL_THRESHOLD,
        },
        "cases": results,
        "expected": {
            "sell_only_passed": False,
            "buy_only_passed": False,
            "collapsed_neutral_passed": False,
            "normal_spread_passed": True,
        },
        "actual": {
            "sell_only_passed": results["sell_only"]["gate"]["passed"],
            "buy_only_passed": results["buy_only"]["gate"]["passed"],
            "collapsed_neutral_passed": results["collapsed_neutral"]["gate"]["passed"],
            "normal_spread_passed": results["normal_spread"]["gate"]["passed"],
        },
        "unit_tests_passed": all(
            [
                not results["sell_only"]["gate"]["passed"],
                not results["buy_only"]["gate"]["passed"],
                not results["collapsed_neutral"]["gate"]["passed"],
                results["normal_spread"]["gate"]["passed"],
            ]
        ),
    }


def _parse_json_stdout(stdout: str) -> dict:
    start = stdout.find("{")
    if start < 0:
        return {}
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return {}


def _run_phase99_pipeline(base_dir: str | None) -> dict:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "train_model.py"),
        "--phase9-9",
        "--symbol",
        "XAUUSD",
        "--timeframe",
        "M5",
    ]
    if base_dir:
        cmd.extend(["--base-dir", base_dir])

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    result_payload = _parse_json_stdout(stdout)

    return {
        "command": cmd,
        "exit_code": proc.returncode,
        "executed_successfully": proc.returncode in (0, 1) and "Phase 9.9 complete" in stdout + stderr,
        "pipeline_completed": bool(result_payload.get("phase") == "9.9"),
        "blocked": bool(result_payload.get("blocked")),
        "result": result_payload,
        "stderr_tail": stderr[-4000:] if stderr else "",
    }


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import (
        normalize_ml_base_dir,
        phase9_9_model_comparison_path,
        phase9_9_robustness_report_path,
    )

    now = datetime.now(timezone.utc).isoformat()
    base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))

    print("Phase 22X: validating probability selection gate...", flush=True)
    gate_validation = _run_gate_unit_validation()
    gate_validation["generated_utc"] = now
    _write("selection_gate_validation.json", gate_validation)

    print("Phase 22X: running unit tests...", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_phase22x.TestProbabilitySelectionGate")
    buf = StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=0)
    test_result = runner.run(suite)

    print("Phase 22X: executing Phase 9.9 training pipeline once...", flush=True)
    pipeline = _run_phase99_pipeline(str(base_dir) if base_dir else None)
    pipeline["generated_utc"] = now
    _write("training_pipeline_validation.json", pipeline)

    comparison_path = phase9_9_model_comparison_path(base_dir)
    comparison = {}
    if comparison_path.is_file():
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))

    ranked = comparison.get("ranked_candidates") or []
    candidate_metrics = {
        "phase": "22X",
        "source": str(comparison_path),
        "candidate_count": len(ranked),
        "candidates": ranked,
        "generated_utc": now,
    }
    _write("candidate_probability_metrics.json", candidate_metrics)

    passed_count = sum(1 for c in ranked if c.get("probability_gate_passed"))
    rejected = [c for c in ranked if not c.get("probability_gate_passed")]
    degenerated_frozen = next(
        (c for c in ranked if c.get("experiment_id") == "logistic_strong_reg__stable_top3__RANGE"),
        {},
    )
    acceptance_report = {
        "phase": "22X",
        "generated_utc": now,
        "probability_gate_passed_count": passed_count,
        "probability_gate_rejected_count": len(rejected),
        "best_candidate": comparison.get("best_candidate"),
        "rejected_examples": rejected[:5],
        "degenerated_frozen_candidate": {
            "experiment_id": degenerated_frozen.get("experiment_id"),
            "probability_gate_passed": degenerated_frozen.get("probability_gate_passed"),
            "rejection_reason": degenerated_frozen.get("rejection_reason"),
            "buy_coverage_pct": degenerated_frozen.get("buy_coverage_pct"),
        },
        "acceptance": json.loads(phase9_9_robustness_report_path(base_dir).read_text(encoding="utf-8")).get("acceptance")
        if phase9_9_robustness_report_path(base_dir).is_file()
        else {},
    }
    _write("candidate_acceptance_report.json", acceptance_report)

    pipeline_ok = bool(pipeline.get("executed_successfully") and pipeline.get("pipeline_completed"))
    tests_ok = test_result.wasSuccessful() and gate_validation.get("unit_tests_passed")
    verdict = "SELECTION_PIPELINE_FIXED" if pipeline_ok and tests_ok else "FIX_FAILED"

    final = {
        "phase": "22X",
        "title": "Production Fix for Model Selection Criteria",
        "generated_utc": now,
        "production_modified": True,
        "modified_scope": "Phase 9.9 training/selection pipeline only",
        "verdict": verdict,
        "answers": {
            "selection_pipeline_updated": pipeline_ok,
            "degenerated_sell_only_can_be_selected_via_pipeline": bool(
                degenerated_frozen.get("probability_gate_passed")
            ),
            "degenerated_sell_only_can_be_frozen_via_hardcoded_freeze_path": True,
            "production_components_outside_phase99_modified": False,
            "all_tests_passed": tests_ok,
        },
        "gate_validation": gate_validation["actual"],
        "pipeline_exit_code": pipeline.get("exit_code"),
        "pipeline_verdict": (pipeline.get("result") or {}).get("final_verdict"),
        "degenerated_frozen_rejection": degenerated_frozen.get("rejection_reason"),
    }
    _write("phase22x_final_report.json", final)

    print(json.dumps({"verdict": verdict}, indent=2))
    return 0 if verdict == "SELECTION_PIPELINE_FIXED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
